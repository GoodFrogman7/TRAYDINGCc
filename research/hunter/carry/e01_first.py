from engine_check import *
import strats as S
rows = []
rows.append(check(S.DiscountBounce(), label="discount z2.5 floor5 exitprem hold36"))
rows.append(check(S.DiscountBounce(), {"exit_prem": False}, label="discount z2.5 no-exit hold36"))
rows.append(check(S.DiscountBounce(), {"z": 2.0}, label="discount z2.0"))
rows.append(check(S.DiscountBounce(), {"z": 3.0}, label="discount z3.0"))
rows.append(check(S.DiscountAbs(), label="discount abs12 hold36"))
rows.append(check(S.DiscountAbs(), {"thr_bp": 8.0}, label="discount abs8"))
rows.append(check(S.HotDip(), label="hotdip 5bp don24 hold24"))
rows.append(check(S.HotDip(), {"thr_bp": 8.0}, label="hotdip 8bp"))
rows.append(check(S.HotDip(), {"thr_bp": 3.0}, label="hotdip 3bp"))
rows.append(check(S.OIWashout(), label="oiwash don72 oi24 -15% hold36"))
rows.append(check(S.OIWashout(), {"oi_drop": 0.10}, label="oiwash -10%"))
rows.append(check(S.OIWashout(), {"oi_drop": 0.20}, label="oiwash -20%"))
rows.append(check(S.RetailCap(), label="retailcap q.10 drop3% hold24"))
rows.append(check(S.RetailCap(), {"q": 0.05}, label="retailcap q.05"))
rows.append(check(S.PremSpikeShort(), label="prem spike short 40bp hold8"))
table(rows)
