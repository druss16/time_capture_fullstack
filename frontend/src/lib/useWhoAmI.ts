// src/lib/useWhoAmI.ts
import { useEffect, useState } from "react";
import { fetchWhoAmI, primeWhoAmIFromCache, type WhoAmI } from "./whoami";

export function useWhoAmI() {
  const [me, setMe] = useState<WhoAmI | null>(primeWhoAmIFromCache());

  useEffect(() => {
    let alive = true;
    // Always force once on first mount so a stale cache can't “log you in”
    fetchWhoAmI(true).then((j) => {
      if (alive) setMe(j);
    });
    return () => {
      alive = false;
    };
  }, []);

  return me;
}