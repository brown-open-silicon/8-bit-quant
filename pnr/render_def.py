# Render a placed/routed DEF (Sky130 HD) to PNG using cell GDS for real-looking cells.
#   klayout -b -r pnr/render_def.py -rd def=<file.def> -rd out=<file.png> [-rd zoom=0.1]
import os
import pya

pdk = os.environ["PDK_ROOT"] + "/sky130A"
hd = pdk + "/libs.ref/sky130_fd_sc_hd"
opt = pya.LoadLayoutOptions()
cfg = opt.lefdef_config
cfg.lef_files = [hd + "/techlef/sky130_fd_sc_hd__nom.tlef", hd + "/lef/sky130_fd_sc_hd.lef"]
cfg.macro_layout_files = [hd + "/gds/sky130_fd_sc_hd.gds"]
cfg.read_lef_with_def = False
cfg.map_file = pdk + "/libs.tech/klayout/tech/sky130A.map"
opt.lefdef_config = cfg

view = pya.LayoutView()
view.load_layout(globals()["def"], opt, True)
view.load_layer_props(pdk + "/libs.tech/klayout/tech/sky130A.lyp")
view.max_hier()
# show only the physical layers: diffusion, poly, local interconnect, metal 1-5
KEEP = {65, 66, 67, 68, 69, 70, 71, 72}
it = view.begin_layers()
while not it.at_end():
    lp = it.current()
    lp.visible = (lp.source_layer in KEEP)
    it.next()
for k, v in (("background-color", "#000000"), ("grid-visible", "false"), ("text-visible", "false")):
    view.set_config(k, v)
top = view.active_cellview().layout().top_cell()
box = top.dbbox()
z = float(globals().get("zoom", 1.0))
if z < 1.0:
    c = box.center()
    box = pya.DBox(c.x - box.width() * z / 2, c.y - box.height() * z / 2,
                   c.x + box.width() * z / 2, c.y + box.height() * z / 2)
view.save_image_with_options(out, 2400, 2400, 0, 0, 0, box, False)
print(f"wrote {out}; die {top.dbbox().width():.0f} x {top.dbbox().height():.0f} um")
