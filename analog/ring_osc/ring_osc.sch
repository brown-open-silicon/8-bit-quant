v {xschem version=3.4.6 file_version=1.2
* 7-stage ring oscillator on Sky130 (transistor level).
* Adapted from the PDK's xschem example sky130_tests/test_inv.sch
* (Copyright 2021 Stefan Frederik Schippers, Apache-2.0).
* Its frequency moves with process, voltage and temperature: the basic
* building block of a PVT sensor. Sweep: analog/ring_osc/sweep.py
}
G {}
K {}
V {}
S {}
E {}
T {7-stage ring oscillator (Sky130, transistor level)} 160 -420 0 0 0.6 0.6 {layer=4}
T {frequency tracks process, voltage, temperature: the core of a PVT sensor} 160 -370 0 0 0.35 0.35 {layer=8}
N 360 -290 360 -130 { lab=Z[2]}
N 440 -290 440 -130 { lab=Z[3]}
N 520 -290 520 -130 { lab=Z[4]}
N 600 -290 600 -130 { lab=Z[5]}
N 680 -290 680 -130 { lab=Z[6]}
N 760 -190 760 -130 { lab=Z[0]}
N 760 -190 820 -190 { lab=Z[0]}
N 820 -190 820 -80 { lab=Z[0]}
N 160 -80 820 -80 { lab=Z[0]}
N 160 -190 160 -80 { lab=Z[0]}
N 160 -190 200 -190 { lab=Z[0]}
N 200 -290 200 -190 { lab=Z[0]}
N 210 -300 760 -300 {bus=true lab=Z[6:0]}
N 280 -290 280 -130 { lab=Z[1]}
C {devices/parax_cap.sym} 280 -120 0 0 {name=C1 gnd=0 value=4f m=1}
C {devices/parax_cap.sym} 360 -120 0 0 {name=C2 gnd=0 value=4f m=1}
C {devices/parax_cap.sym} 440 -120 0 0 {name=C3 gnd=0 value=4f m=1}
C {devices/parax_cap.sym} 520 -120 0 0 {name=C4 gnd=0 value=4f m=1}
C {devices/parax_cap.sym} 600 -120 0 0 {name=C5 gnd=0 value=4f m=1}
C {devices/parax_cap.sym} 680 -120 0 0 {name=C6 gnd=0 value=4f m=1}
C {devices/parax_cap.sym} 760 -120 0 0 {name=C7 gnd=0 value=4.01f m=1}
C {devices/lab_pin.sym} 760 -300 0 1 {name=l9 sig_type=std_logic lab=Z[6:0]}
C {sky130_tests/not.sym} 240 -190 0 0 {name=x4 m=1 VCCPIN=VCC VSSPIN=VSS W_N=WN L_N=0.15 W_P=WP L_P=0.15}
C {sky130_tests/not.sym} 320 -190 0 0 {name=x1 m=1 VCCPIN=VCC VSSPIN=VSS W_N=WN L_N=0.15 W_P=WP L_P=0.15}
C {sky130_tests/not.sym} 400 -190 0 0 {name=x2 m=1 VCCPIN=VCC VSSPIN=VSS W_N=WN L_N=0.15 W_P=WP L_P=0.15}
C {sky130_tests/not.sym} 480 -190 0 0 {name=x3 m=1 VCCPIN=VCC VSSPIN=VSS W_N=WN L_N=0.15 W_P=WP L_P=0.15}
C {sky130_tests/not.sym} 560 -190 0 0 {name=x5 m=1 VCCPIN=VCC VSSPIN=VSS W_N=WN L_N=0.15 W_P=WP L_P=0.15}
C {sky130_tests/not.sym} 640 -190 0 0 {name=x6 m=1 VCCPIN=VCC VSSPIN=VSS W_N=WN L_N=0.15 W_P=WP L_P=0.15}
C {sky130_tests/not.sym} 720 -190 0 0 {name=x7 m=1 VCCPIN=VCC VSSPIN=VSS W_N=WN L_N=0.15 W_P=WP L_P=0.15}
C {devices/bus_tap.sym} 210 -300 3 1 {name=l19 lab=[0]}
C {devices/bus_tap.sym} 290 -300 3 1 {name=l2 lab=[1]}
C {devices/bus_tap.sym} 370 -300 3 1 {name=l3 lab=[2]}
C {devices/bus_tap.sym} 450 -300 3 1 {name=l4 lab=[3]}
C {devices/bus_tap.sym} 530 -300 3 1 {name=l5 lab=[4]}
C {devices/bus_tap.sym} 610 -300 3 1 {name=l6 lab=[5]}
C {devices/bus_tap.sym} 690 -300 3 1 {name=l7 lab=[6]}
C {devices/simulator_commands_shown.sym} 900 -420 0 0 {name=COMMANDS
simulator=ngspice
only_toplevel=false
value=".param VCC=1.8 WN=1 WP=2
vvss vss 0 dc 0
vvcc vcc 0 pwl 0 0 0.5n 'VCC'
.control
  tran 2p 8n
  meas tran t2per TRIG v(\\"z[0]\\") VAL=0.9 RISE=3 TARG v(\\"z[0]\\") VAL=0.9 RISE=5
  print 2/t2per
  wrdata ring_osc_tran.txt v(\\"z[0]\\") v(\\"z[3]\\")
.endc
"}
C {devices/code.sym} 900 -160 0 0 {name=MODELS
only_toplevel=true
format="tcleval( @value )"
value="
.lib $::SKYWATER_MODELS/sky130.lib.spice tt
"
spice_ignore=false}
