"""Revolved (lathed) widget geometry with an analytic silhouette.

Give it a profile -- one or more chains of (radius, z) pairs -- and it
revolves them into a shaded solid and can draw a true outline for it. Any
tool wanting a 3D placement marker can supply its own profile.

Drawn from a POST_VIEW handler: coordinates are world space and Blender
supplies the view matrix, which sidesteps the window-vs-region coordinate
problem that plagues 2D overlay drawing entirely.
"""

import math

import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

_TRI_SHADER = gpu.shader.from_builtin('SMOOTH_COLOR')


class Lathe:
    """A surface of revolution built from a profile, cached on first use.

    `chains` is a sequence of chains, each a sequence of (radius, z). Separate
    chains leave gaps in the surface -- useful for a cut-out in a stem.

    `height` normalises the profile: geometry comes out spanning z 0..1, so
    drawing at a given height scales it exactly.

    Segments default high because a GPU overlay gets no antialiasing of its
    own -- POST_VIEW draws land after the viewport's TAA resolve and the gpu
    module exposes no MSAA state. The only lever on silhouette aliasing is
    making the facets small enough to be sub-pixel.
    """

    def __init__(self, chains, profile_height, segments=64):
        self.chains = tuple(tuple(chain) for chain in chains)
        self.profile_height = profile_height
        self.segments = segments
        self._cache = None

    # --- geometry ---------------------------------------------------------

    def _revolve(self, profile):
        """Lathe one profile chain into triangles with smooth normals.

        Normals are averaged per position rather than per face, so the
        surface shades as a rounded solid instead of showing its facets.
        """
        rings = []
        for radius, z in profile:
            ring = []
            for i in range(self.segments):
                angle = (i / self.segments) * math.tau
                ring.append(Vector((
                    radius * math.cos(angle), radius * math.sin(angle), z,
                )))
            rings.append(ring)

        faces = []
        for lower, upper in zip(rings, rings[1:]):
            for i in range(self.segments):
                j = (i + 1) % self.segments
                a, b, c, d = lower[i], lower[j], upper[j], upper[i]
                faces.append((a, b, c))
                faces.append((a, c, d))

        accum = {}
        for tri in faces:
            normal = (tri[1] - tri[0]).cross(tri[2] - tri[0])
            if normal.length <= 1e-9:
                continue
            normal.normalize()
            for point in tri:
                key = (round(point.x, 5), round(point.y, 5), round(point.z, 5))
                accum[key] = accum.get(key, Vector((0.0, 0.0, 0.0))) + normal

        verts, normals = [], []
        for tri in faces:
            for point in tri:
                key = (round(point.x, 5), round(point.y, 5), round(point.z, 5))
                smooth = accum.get(key)
                smooth = (
                    smooth.normalized() if smooth and smooth.length > 1e-9
                    else Vector((0.0, 0.0, 1.0))
                )
                verts.append(point)
                normals.append(smooth)
        return verts, normals

    def geometry(self):
        if self._cache is None:
            verts, normals = [], []
            for chain in self.chains:
                v, n = self._revolve(chain)
                verts.extend(v)
                normals.extend(n)
            inv = 1.0 / self.profile_height
            self._cache = ([v * inv for v in verts], normals)
        return self._cache

    @staticmethod
    def frame(axis):
        """Orthonormal (u, v, w) with w = axis, for placing the profile.

        The lathe is authored about +Z, but a marker standing on a vertical
        drawing plane has to stand along that plane's normal instead, so
        every placement goes through this frame rather than assuming Z.
        """
        w = axis.normalized()
        # Any vector not parallel to w works as a seed; pick the world axis
        # w is least aligned with so the cross product stays well-conditioned.
        seed = (
            Vector((0.0, 0.0, 1.0)) if abs(w.z) < 0.9
            else Vector((1.0, 0.0, 0.0))
        )
        u = seed.cross(w)
        if u.length <= 1e-9:
            u = Vector((1.0, 0.0, 0.0))
        u.normalize()
        v = w.cross(u)
        return u, v, w

    def place(self, base, height, point, axis=None):
        """Map a normalised profile point into world space."""
        scale = height
        if axis is None:
            return base + Vector((
                point.x * scale, point.y * scale, point.z * scale,
            ))
        u, v, w = self.frame(axis)
        return base + (u * point.x + v * point.y + w * point.z) * scale

    def anchor(self, base, height, profile_z, axis=None):
        """World point at a given profile height, scaled and placed."""
        offset = profile_z * (height / self.profile_height)
        if axis is None:
            return base + Vector((0.0, 0.0, offset))
        return base + axis.normalized() * offset

    # --- silhouette -------------------------------------------------------

    def _rim_radii(self, profile):
        """Profile vertices whose radius is a local maximum.

        These rings are what reads as the outline when the widget is viewed
        down its own axis, where the side profile degenerates to a point.
        """
        out = []
        for i, (radius, z) in enumerate(profile):
            prev_r = profile[i - 1][0] if i > 0 else -1.0
            next_r = profile[i + 1][0] if i + 1 < len(profile) else -1.0
            if radius > 0.0 and radius >= prev_r and radius >= next_r:
                out.append((radius, z))
        return out

    def outline(self, base, height, view_vector, axis=None):
        """Exact silhouette, as world-space polylines.

        A surface of revolution has an analytic silhouette, so there is no
        need to approximate one with a fresnel band -- which is not a
        silhouette at all and reads inconsistently between parts. `N . V`
        selects surfaces *perpendicular* to the view, so a cylinder viewed
        end-on turns entirely "rim" while a cone viewed the same way turns
        entirely transparent.

        The true outline is where N . V crosses zero: side-on that is the
        profile drawn at the two azimuths 90 degrees off the view direction;
        axis-on the profile collapses and it becomes the rings at the widest
        points. Both are emitted, so whichever is degenerate contributes
        nothing and the outline stays stable as the camera swings between.
        """
        scale = height / self.profile_height
        u, v, w = self.frame(
            axis if axis is not None else Vector((0.0, 0.0, 1.0))
        )
        # Azimuth of the view within the lathe's own (u, v) plane, so the
        # silhouette stays correct when the marker is not standing on Z.
        azimuth = math.atan2(view_vector.dot(v), view_vector.dot(u))

        def at(radius, z, angle):
            offset = (u * math.cos(angle) + v * math.sin(angle)) \
                * (radius * scale) + w * (z * scale)
            return (base.x + offset.x, base.y + offset.y, base.z + offset.z)

        strips = []
        for profile in self.chains:
            for side in (azimuth + math.pi * 0.5, azimuth - math.pi * 0.5):
                strips.append([at(radius, z, side) for radius, z in profile])

        rings = []
        for profile in self.chains:
            for radius, z in self._rim_radii(profile):
                rings.append([
                    at(radius, z, (i / 32) * math.tau) for i in range(33)
                ])

        return strips, rings

    # --- drawing ----------------------------------------------------------

    def draw(self, base, height, view_vector, color=(1.0, 1.0, 1.0),
             alpha=0.5, hollow=False, axis=None):
        """Draw standing on `base`, `height` tall. POST_VIEW only.

        `hollow` renders the body as a faint volume hint and draws the real
        silhouette as lines -- lines because they are the actual outline, and
        because the polyline shader antialiases itself where overlay triangle
        edges never do.
        """
        from .draw import draw_lines_3d

        verts, normals = self.geometry()
        body_alpha = alpha * 0.22 if hollow else alpha

        rotate = None
        if axis is not None:
            rotate = self.frame(axis)

        coords, colors = [], []
        for point, normal in zip(verts, normals):
            if rotate is None:
                world = Vector((
                    base.x + point.x * height,
                    base.y + point.y * height,
                    base.z + point.z * height,
                ))
                world_normal = normal
            else:
                u, v, w = rotate
                world = base + (
                    u * point.x + v * point.y + w * point.z
                ) * height
                world_normal = (
                    u * normal.x + v * normal.y + w * normal.z
                )
            coords.append((world.x, world.y, world.z))
            # Headlight lambert; there is no lighting for a GPU overlay, so
            # without it the lathe reads as a flat silhouette.
            shade = 0.45 + 0.55 * abs(world_normal.dot(view_vector))
            colors.append((
                color[0] * shade, color[1] * shade, color[2] * shade,
                body_alpha,
            ))

        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.face_culling_set('NONE')
        batch = batch_for_shader(
            _TRI_SHADER, 'TRIS', {"pos": coords, "color": colors},
        )
        _TRI_SHADER.bind()
        batch.draw(_TRI_SHADER)
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')

        if hollow:
            strips, rings = self.outline(base, height, view_vector, axis)
            line_color = (*color, min(1.0, alpha * 1.6))
            for polyline in strips + rings:
                draw_lines_3d(polyline, line_color, width=1.8)
