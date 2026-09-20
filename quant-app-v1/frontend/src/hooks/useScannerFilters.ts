import { useState, useEffect } from "react";

export type FilterPreset = { id: string; name: string; active: boolean };

export default function useScannerFilters() {
  const [presets, setPresets] = useState<FilterPreset[]>(() => {
    try { return JSON.parse(localStorage.getItem("gw_scanner_presets") || "[]"); } catch { return []; }
  });
  useEffect(() => { localStorage.setItem("gw_scanner_presets", JSON.stringify(presets)); }, [presets]);
  const add = (name: string) => setPresets((p) => [...p, { id: Math.random().toString(36).slice(2), name, active: false }]);
  return { presets, add };
}
