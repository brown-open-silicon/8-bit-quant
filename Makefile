.PHONY: all quant sim area shell coral clean

all: quant sim area

quant:        ## train MLP, compare int8/int4/ternary, fault-inject, export golden vectors
	uv run python quant/experiment.py

sim:          ## run cocotb RTL tests against golden vectors (in EDA container)
	scripts/eda.sh python3 tb/run.py

area:         ## synthesize blocks to Sky130 cells (PDK=gf180mcuD for GF180), report area
	scripts/eda.sh synth/area.sh

shell:        ## interactive shell in the EDA container, repo at /work
	scripts/eda.sh

coral:        ## fetch Coral NPU source (git submodule)
	git submodule update --init --depth 1 third_party/coralnpu

clean:
	rm -rf build sim_build results.xml
