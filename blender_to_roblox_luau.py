# Blender -> Roblox EditableMesh import-script generator (v2, with instancing).
# Run INSIDE Blender (via Blender MCP execute_code). Reads all objects whose
# names start with PREFIX, emits a complete Luau script that rebuilds them as
# flat-shaded MeshParts in Roblox Studio (run it with robloxstudio execute_luau,
# target "edit"). No asset upload / API key needed; mesh bakes into the place file.
#
# v2: objects sharing mesh data (linked duplicates) are exported ONCE and
# re-placed as MeshPart:Clone()s with full rotation CFrames — keeps the Luau
# small for stacks/piles/forests of repeated parts.
#
# Gotchas encoded here (learned 2026-08-19):
# - Verts DUPLICATED per triangle -> unshared normals -> crisp flat shading.
# - CreateMeshPartAsync centers geometry on its bbox; verts are emitted relative
#   to the base object's bbox center c0, and each instance's CFrame is
#   R'*c0 + t' with rotation R' -- reassembles exactly.
# - Axis map Blender Z-up -> Roblox Y-up: A = (x, z, -y). R' = A R A^T, t' = A t * SCALE.
# - Colors: Blender linear base color -> Roblox Color3 via gamma ** (1/2.2).
import bpy
from mathutils import Matrix, Vector

PREFIX = "Cuke_"                  # object name prefix to export
MODEL_NAME = "CucumberWhole"      # workspace model name in Roblox
SCALE = 3.0                       # blender units -> studs
COLLIDE_MATCH = "Body"            # substring: parts whose name contains this get CanCollide
OFFSET = (14, 0, -18)             # placement offset (studs) from the spawn pad
OUT = "C:/Users/shrey/Documents/BlenderExports/roblox_import.lua"

A = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))  # blender world -> roblox axes

def srgb(c):
    return tuple(round(max(0.0, min(1.0, ch)) ** (1 / 2.2), 3) for ch in c[:3])

def obj_color(o):
    if o.data.materials and o.data.materials[0] and o.data.materials[0].use_nodes:
        bsdf = o.data.materials[0].node_tree.nodes.get("Principled BSDF")
        if bsdf:
            return srgb(bsdf.inputs["Base Color"].default_value)
    return (0.5, 0.5, 0.5)

objs = sorted([o for o in bpy.data.objects if o.name.startswith(PREFIX)], key=lambda o: o.name)

# recenter: the whole model's bottom-center lands at baseCF, regardless of
# where it sits in the Blender scene
gmin = [1e9] * 3
gmax = [-1e9] * 3
for o in objs:
    mw = o.matrix_world
    for v in o.data.vertices:
        p = (A @ (mw @ v.co)) * SCALE
        for k in range(3):
            gmin[k] = min(gmin[k], p[k])
            gmax[k] = max(gmax[k], p[k])
recenter = Vector(((gmin[0] + gmax[0]) / 2, gmin[1], (gmin[2] + gmax[2]) / 2))

geom_index = {}   # mesh-data name -> (index, base_obj, c0)
geom_verts = []   # flat vert lists, one per unique mesh
instances = []    # (name, color, geom index, 12-number CFrame)

for o in objs:
    key = o.data.name
    if key not in geom_index:
        mesh = o.data
        mesh.calc_loop_triangles()
        mw = o.matrix_world
        conv = [(A @ (mw @ v.co)) * SCALE for v in mesh.vertices]
        xs = [v.x for v in conv]; ys = [v.y for v in conv]; zs = [v.z for v in conv]
        c0 = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2))
        local = [v - c0 for v in conv]
        flat = []
        for t in mesh.loop_triangles:
            for vi in t.vertices:
                p = local[vi]
                flat.extend((p.x, p.y, p.z))
        geom_index[key] = (len(geom_verts), o, c0)
        geom_verts.append(flat)
    gi, base, c0 = geom_index[key]
    W = o.matrix_world @ base.matrix_world.inverted()
    Rp = A @ W.to_3x3() @ A.transposed()
    tp = (A @ W.to_translation()) * SCALE
    x = Rp @ c0 + tp - recenter
    cf = [x.x, x.y, x.z,
          Rp[0][0], Rp[0][1], Rp[0][2],
          Rp[1][0], Rp[1][1], Rp[1][2],
          Rp[2][0], Rp[2][1], Rp[2][2]]
    instances.append((o.name, obj_color(o), gi, cf))

def fmt(nums, nd=3):
    return ",".join(str(round(n, nd)) for n in nums)

lines = ['local AssetService = game:GetService("AssetService")', 'local geoms = {']
for flat in geom_verts:
    lines.append('{%s},' % fmt(flat))
lines.append('}')
lines.append('local instances = {')
for name, col, gi, cf in instances:
    lines.append('{name="%s",color={%s},g=%d,cf={%s}},' % (name, fmt(col), gi + 1, fmt(cf, 4)))
lines.append('}')
lines.append('''
local spawnLoc = workspace:FindFirstChildWhichIsA("SpawnLocation", true)
local baseCF
if spawnLoc then
    local groundY = spawnLoc.Position.Y - spawnLoc.Size.Y / 2
    baseCF = CFrame.new(spawnLoc.Position.X + %OX%, groundY + %OY%, spawnLoc.Position.Z + %OZ%)
else
    baseCF = CFrame.new(%OX%, %OY%, %OZ%)
end

local templates = {}
for i, g in ipairs(geoms) do
    local em = AssetService:CreateEditableMesh()
    for j = 1, #g, 9 do
        local a = em:AddVertex(Vector3.new(g[j], g[j+1], g[j+2]))
        local b = em:AddVertex(Vector3.new(g[j+3], g[j+4], g[j+5]))
        local c = em:AddVertex(Vector3.new(g[j+6], g[j+7], g[j+8]))
        em:AddTriangle(a, b, c)
    end
    local ok, mp = pcall(function()
        return AssetService:CreateMeshPartAsync(Content.fromObject(em))
    end)
    if not ok then
        error("CreateMeshPartAsync failed for geom " .. i .. ": " .. tostring(mp))
    end
    templates[i] = mp
end

local old = workspace:FindFirstChild("%MODEL%")
if old then old:Destroy() end

local model = Instance.new("Model")
model.Name = "%MODEL%"

for _, inst in ipairs(instances) do
    local mp = templates[inst.g]:Clone()
    mp.Name = inst.name
    mp.Color = Color3.new(inst.color[1], inst.color[2], inst.color[3])
    mp.Material = Enum.Material.SmoothPlastic
    mp.Anchored = true
    mp.CanCollide = (string.find(inst.name, "%COLLIDEM%", 1, true) ~= nil)
    mp.CFrame = baseCF * CFrame.new(table.unpack(inst.cf))
    mp.Parent = model
    if not model.PrimaryPart and mp.CanCollide then model.PrimaryPart = mp end
end

for _, t in ipairs(templates) do t:Destroy() end

model.Parent = workspace

-- frame the studio camera on it (Focus matters or Studio re-levels the pitch)
local pos = baseCF.Position
local cam = workspace.CurrentCamera
cam.CFrame = CFrame.lookAt(pos + Vector3.new(12, 11, 12), pos + Vector3.new(0, 3, 0))
cam.Focus = CFrame.new(pos + Vector3.new(0, 3, 0))
print("IMPORTED %MODEL% at", tostring(pos), "parts:", #model:GetChildren(), "unique geoms:", #geoms)
'''.replace("%MODEL%", MODEL_NAME).replace("%COLLIDEM%", COLLIDE_MATCH)
   .replace("%OX%", str(OFFSET[0])).replace("%OY%", str(OFFSET[1])).replace("%OZ%", str(OFFSET[2])))

with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("LUAU_WRITTEN geoms=%d instances=%d" % (len(geom_verts), len(instances)))
