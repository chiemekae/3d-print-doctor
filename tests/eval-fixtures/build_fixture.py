"""Build the eval fixture project: the test bracket's mesh with another project's settings.

  openscad --export-format asciistl -o test-bracket.stl test-bracket.scad
  build_fixture.py test-bracket.stl SETTINGS.3mf test-bracket.3mf [--rename-presets OLD=NEW]
  OrcaSlicer --allow-mix-temp --slice 0 --export-3mf test-bracket.gcode.3mf test-bracket.3mf

SETTINGS.3mf supplies Metadata/project_settings.config: the fixture used a PLA project with PETG
supports at zero top gap, bed_temperature_formula by_highest_temp, and flush_into_infill on.
--rename-presets replaces a preset-name prefix (e.g. a personal one) so it isn't published.
"""
import sys, zipfile, re
args = [a for a in sys.argv[1:] if not a.startswith("--rename-presets")]
stl, settings_src, out = args[0], args[1], args[2]
renames = [a.split("=", 1)[1].split("=", 1) for a in sys.argv[1:] if a.startswith("--rename-presets=")]

# ASCII STL -> deduplicated vertices and triangles, shifted so the part's footprint is centered at the origin, z from 0
verts, index, tris = [], {}, []
for tri in re.findall(r"outer loop(.*?)endloop", open(stl).read(), re.S):
    ids = []
    for v in re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", tri):
        key = tuple(round(float(c), 5) for c in v)
        if key not in index: index[key] = len(verts); verts.append(key)
        ids.append(index[key])
    tris.append(ids)
xs, ys, zs = zip(*verts)
cx, cy, z0 = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, min(zs)
verts = [(x - cx, y - cy, z - z0) for x, y, z in verts]

NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
      'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
      'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')
mesh = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" ' + NS + '>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n'
        '  <object id="1" p:UUID="00010000-81cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <mesh>\n    <vertices>\n'
        + "".join(f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>\n' for x, y, z in verts)
        + '    </vertices>\n    <triangles>\n'
        + "".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>\n' for a, b, c in tris)
        + '    </triangles>\n   </mesh>\n  </object>\n </resources>\n <build/>\n</model>\n')
top = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" ' + NS + '>\n'
       ' <metadata name="Application">BambuStudio-2.3.1</metadata>\n <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
       ' <metadata name="Title">test-bracket</metadata>\n <metadata name="License">MIT</metadata>\n'
       ' <resources>\n  <object id="2" p:UUID="00000001-61cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <components>\n'
       '    <component p:path="/3D/Objects/test-bracket.model" objectid="1" p:UUID="00010000-b206-40ff-9872-83e8017abed1" '
       'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n   </components>\n  </object>\n </resources>\n'
       ' <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">\n'
       '  <item objectid="2" p:UUID="00000002-b1ec-4553-aec9-835e5b724bb4" transform="1 0 0 0 1 0 0 0 1 128 128 0" printable="1"/>\n'
       ' </build>\n</model>\n')
rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Target="/3D/Objects/test-bracket.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        '</Relationships>\n')
root_rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
             ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
             '</Relationships>\n')
model_settings = '''<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="2">
    <metadata key="name" value="test-bracket"/>
    <metadata key="extruder" value="1"/>
    <part id="1" subtype="normal_part">
      <metadata key="name" value="test-bracket"/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
    </part>
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="filament_maps" value="1 1"/>
    <model_instance>
      <metadata key="object_id" value="2"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="100"/>
    </model_instance>
  </plate>
  <assemble>
   <assemble_item object_id="2" instance_id="0" transform="1 0 0 0 1 0 0 0 1 0 0 0" offset="0 0 0" />
  </assemble>
</config>
'''
src = zipfile.ZipFile(settings_src)
settings = src.read("Metadata/project_settings.config").decode()
for old, new in renames:
    settings = settings.replace(old, new)
content_types = src.read("[Content_Types].xml")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", content_types)
    z.writestr("_rels/.rels", root_rels)
    z.writestr("3D/3dmodel.model", top)
    z.writestr("3D/_rels/3dmodel.model.rels", rels)
    z.writestr("3D/Objects/test-bracket.model", mesh)
    z.writestr("Metadata/project_settings.config", settings)
    z.writestr("Metadata/model_settings.config", model_settings)
    z.writestr("Metadata/slice_info.config", src.read("Metadata/slice_info.config"))
print(len(verts), "vertices,", len(tris), "triangles; bbox x", round(max(xs) - min(xs), 1), "y", round(max(ys) - min(ys), 1), "z", round(max(zs) - z0, 1))
