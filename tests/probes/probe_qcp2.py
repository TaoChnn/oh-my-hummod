# Probe 2: attach QCP via Bridge, test Go/Stop completion semantics.
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "..")))
from oh_my_hummod.bridge import Bridge

ENGINE = os.environ.get("HUMMOD_ENGINE_DIR") or sys.argv[1]
b = Bridge(ENGINE, exe_name="QCP 2005.EXE")
print("attach:", b.attach(), "pid:", b.pid)
b.wait_ready("Help", timeout=15)
tree = b.menu_tree()

go1min = tree.walk("Go/1 Min").cmd_id
stop_id = tree.walk("Stop").cmd_id
cont_id = tree.walk("Continue").cmd_id
print("Go/1 Min:", go1min, "| Stop:", stop_id, "| Continue:", cont_id)
print("Stop enabled before:", b.menu_item_enabled(stop_id))

t0 = time.time()
b.command(go1min)
for i in range(100):
    time.sleep(0.3)
    if not b.menu_item_enabled(stop_id):
        print(f"finished after ~{time.time()-t0:.1f}s (Stop grayed)")
        break
else:
    print("Stop still enabled after 30s!?")

print("Stop enabled after :", b.menu_item_enabled(stop_id))
print("Continue enabled   :", b.menu_item_enabled(cont_id))

# restart settle
b.command(tree.walk("Restart").cmd_id)
time.sleep(2)
print("after Restart: Stop enabled =", b.menu_item_enabled(stop_id))
print("QCP_PROBE_OK")
