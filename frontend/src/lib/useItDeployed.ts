/**
 * Is this firm rolled out by its own IT department?
 *
 * A provisioning map or a live deployment token both mean an MSI exists and
 * machines are meant to arrive already paired. Offering someone a pairing code
 * there asks them to work around their IT department — and a device paired by
 * hand never matches the provisioning map, so it also breaks the very report
 * that tells us whether the rollout worked.
 *
 * Returns null while unknown, so callers can render neither branch rather than
 * flashing the wrong one.
 */
import { useEffect, useState } from "react";
import { safeFetchJson, API_BASE } from "@/lib/api";

export function useItDeployed(): boolean | null {
  const [value, setValue] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    safeFetchJson<{ it_deployed?: boolean }>(`${API_BASE}/capture-status/`)
      .then((s) => !cancelled && setValue(!!s?.it_deployed))
      // Unknown stays unknown. Guessing "self-serve" would put a pairing code
      // in front of someone whose IT department owns that decision.
      .catch(() => !cancelled && setValue(null));
    return () => {
      cancelled = true;
    };
  }, []);
  return value;
}
