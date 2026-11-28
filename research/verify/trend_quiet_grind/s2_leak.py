from vcommon import *
t0=time.time()
market = load_market(end=VALIDATION_END)
for seed in (1, 7, 42):
    with store.ceiling(VALIDATION_END):
        r = harness.leak_test(STRATEGY, market.data, n_targeted=70, n_other=8, n_random=4, seed=seed)
    print("seed", seed, {k: r[k] for k in ("passed","mismatches","probes","cells","forbidden_code")}, r["examples"][:2], round(time.time()-t0,1), flush=True)
