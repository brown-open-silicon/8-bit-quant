# Render a GDS to PNG with KLayout (batch mode, no GUI).
#   klayout -b -r pnr/render.py -rd gds=<file.gds> -rd out=<file.png> [-rd lyp=<layers.lyp>]
#        [-rd zoom=<fraction of die, e.g. 0.15>] [-rd px=2400]
import pya

view = pya.LayoutView()
view.load_layout(gds, True)
if "lyp" in globals() and lyp:
    view.load_layer_props(lyp)
view.max_hier()
view.set_config("background-color", "#ffffff")
view.set_config("grid-visible", "false")
view.set_config("text-visible", "false")
box = view.active_cellview().layout().top_cell().dbbox()
z = float(zoom) if "zoom" in globals() else 1.0
if z < 1.0:
    c = box.center()
    w, h = box.width() * z, box.height() * z
    box = pya.DBox(c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2)
n = int(px) if "px" in globals() else 2400
view.save_image_with_options(out, n, n, 0, 0, 0, box, False)
print(f"wrote {out}  die = {view.active_cellview().layout().top_cell().dbbox()}")
