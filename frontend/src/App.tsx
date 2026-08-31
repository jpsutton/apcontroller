import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiGetText, apiPost, apiPostJson, apiPutJson } from "./api";
import type {
  ActivityPoint,
  ClientRow,
  GlobalSection,
  Group,
  Host,
  RootConfig,
  StatusHost,
  Vlan,
  Wifi,
} from "./types";

const ENCRYPTIONS = [
  "sae",
  "sae-mixed",
  "psk2",
  "psk2+ccmp",
  "psk2+tkip",
  "psk",
  "psk+ccmp",
  "psk+tkip",
  "psk-mixed+ccmp",
  "psk-mixed+tkip",
  "owe",
  "none",
] as const;

function nextHostId(hosts: Host[]): string {
  let n = hosts.length + 1;
  while (hosts.some((h) => h.id === `host${n}`)) n++;
  return `host${n}`;
}

function nextWifiId(wifis: Wifi[]): string {
  let n = wifis.length + 1;
  while (wifis.some((w) => w.id === `wifi${n}`)) n++;
  return `wifi${n}`;
}

function nextVlanId(vlans: Vlan[]): string {
  let n = vlans.length + 1;
  while (vlans.some((v) => v.id === `vlan${n}`)) n++;
  return `vlan${n}`;
}

function nextGroupId(groups: Group[]): string {
  let n = groups.length + 1;
  while (groups.some((g) => g.id === `group${n}`)) n++;
  return `group${n}`;
}

function hostLineState(
  row: StatusHost | undefined,
  intervalMin: number,
): "unknown" | "online" | "offline" {
  if (!row || row.lastcontact < 0) return "unknown";
  const threshold = intervalMin * 2.5 * 60;
  return row.lastcontact > threshold ? "offline" : "online";
}

export default function App() {
  const [tab, setTab] = useState<"devices" | "wifi" | "vlans" | "groups" | "settings">("devices");
  const [cfg, setCfg] = useState<RootConfig | null>(null);
  const [status, setStatus] = useState<{ hosts: StatusHost[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [modal, setModal] = useState<React.ReactNode>(null);

  const refresh = useCallback(async () => {
    setErr(null);
    try {
      const [c, s] = await Promise.all([
        apiGet<RootConfig>("/api/v1/config"),
        apiGet<{ hosts: StatusHost[] }>("/api/v1/status?include_secrets=true"),
      ]);
      setCfg(c);
      setStatus(s);
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    // Show cached status immediately, then poll the devices so the list
    // reflects live reachability instead of stale "Unknown" entries on load.
    void (async () => {
      await refresh();
      try {
        await apiPost("/api/v1/poll");
      } catch {
        // A failed poll just leaves the cached status in place.
      }
      await refresh();
    })();
  }, [refresh]);

  const statusBySection = useMemo(() => {
    const m = new Map<string, StatusHost>();
    status?.hosts.forEach((h) => m.set(h.section, h));
    return m;
  }, [status]);

  const save = async (next: RootConfig) => {
    setErr(null);
    setMsg(null);
    try {
      await apiPutJson("/api/v1/config", next);
      setCfg(next);
      setMsg("Saved.");
      await refresh();
    } catch (e) {
      setErr(String(e));
    }
  };

  const clients: { ap: string; band: number; c: ClientRow }[] = useMemo(() => {
    if (!cfg || !status) return [];
    const out: { ap: string; band: number; c: ClientRow }[] = [];
    for (const h of status.hosts) {
      const name = cfg.hosts.find((x) => x.id === h.section)?.name ?? h.section;
      for (const band of [2, 5, 6] as const) {
        const key = `clientslist${band}g` as keyof StatusHost;
        const list = h[key] as ClientRow[] | undefined;
        list?.forEach((c) => out.push({ ap: name, band, c }));
      }
    }
    return out;
  }, [cfg, status]);

  if (!cfg) {
    return (
      <div className="app">
        <p>Loading…</p>
        {err && <p className="err">{err}</p>}
      </div>
    );
  }

  return (
    <div className="app">
      <h1>AP Controller</h1>
      {err && <p className="err">{err}</p>}
      {msg && <p className="ok">{msg}</p>}
      <div className="tabbed">
        <div className="tabs">
          {(
            [
              ["devices", "Devices"],
              ["wifi", "Wi-Fi"],
              ["vlans", "VLANs"],
              ["groups", "AP Groups"],
              ["settings", "Settings"],
            ] as const
          ).map(([k, l]) => (
            <button key={k} type="button" className={tab === k ? "active" : ""} onClick={() => setTab(k)}>
              {l}
            </button>
          ))}
        </div>

        <div className="panel">
          {tab === "devices" && (
            <DevicesTab
              cfg={cfg}
              statusBySection={statusBySection}
              clients={clients}
              clientCols={cfg.global.clientcolumn}
              onSave={save}
              onRefresh={refresh}
              setModal={setModal}
            />
          )}
          {tab === "wifi" && <WifiTab cfg={cfg} onSave={save} />}
          {tab === "vlans" && <VlansTab cfg={cfg} onSave={save} />}
          {tab === "groups" && <GroupsTab cfg={cfg} onSave={save} setModal={setModal} />}
          {tab === "settings" && (
            <SettingsTab
              cfg={cfg}
              onSave={save}
              onReloadScript={async () => {
                const t = await apiGetText("/api/v1/additional-script");
                setCfg({ ...cfg, additional_script: t });
              }}
            />
          )}
        </div>
      </div>

      {modal && (
        <div
          className="modal-back"
          role="presentation"
          onClick={(e) => {
            if (e.target === e.currentTarget) setModal(null);
          }}
        >
          <div className="modal">{modal}</div>
        </div>
      )}
    </div>
  );
}

function DevicesTab({
  cfg,
  statusBySection,
  clients,
  clientCols,
  onSave,
  onRefresh,
  setModal,
}: {
  cfg: RootConfig;
  statusBySection: Map<string, StatusHost>;
  clients: { ap: string; band: number; c: ClientRow }[];
  clientCols: string[];
  onSave: (c: RootConfig) => Promise<void>;
  onRefresh: () => Promise<void>;
  setModal: (n: React.ReactNode) => void;
}) {
  const [editing, setEditing] = useState<Host | null>(null);
  const iv = cfg.global.interval;

  let online = 0,
    offline = 0,
    unk = 0;
  for (const h of cfg.hosts) {
    const st = hostLineState(statusBySection.get(h.id), iv);
    if (st === "online") online++;
    else if (st === "offline") offline++;
    else unk++;
  }

  return (
    <section>
      <div className="stats">
        <div className="stat">
          All<strong>{cfg.hosts.length}</strong>
        </div>
        <div className="stat" style={{ color: "#15803d" }}>
          Online<strong>{online}</strong>
        </div>
        <div className="stat" style={{ color: "#b91c1c" }}>
          Offline<strong>{offline}</strong>
        </div>
        <div className="stat" style={{ color: "#6b7280" }}>
          Unknown<strong>{unk}</strong>
        </div>
      </div>
      <div className="actions" style={{ marginBottom: "0.75rem" }}>
        <button type="button" onClick={() => void onRefresh()}>
          Refresh status
        </button>
        <button
          type="button"
          onClick={async () => {
            await apiPost("/api/v1/poll");
            await onRefresh();
          }}
        >
          Poll devices now
        </button>
        <button
          type="button"
          className="btn-positive"
          onClick={() => {
            const nh: Host = {
              id: nextHostId(cfg.hosts),
              enabled: true,
              name: "",
              ipaddr: "",
              port: 22,
              username: "root",
              password: "",
              usekeyfile: false,
              keyfile: "/root/.ssh/id_dropbear",
              url: "",
              trunk_port: "",
              mgmt_vlan: 1,
              dumb_ap: true,
            };
            void onSave({ ...cfg, hosts: [...cfg.hosts, nh] });
            setEditing(nh);
          }}
        >
          Add device
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Enabled</th>
            <th>Name</th>
            <th>Address</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {cfg.hosts.map((h) => {
            const row = statusBySection.get(h.id);
            const st = hostLineState(row, iv);
            const label =
              st === "online" ? "● Online" : st === "offline" ? "● Offline" : "— Unknown";
            const disabled = st === "unknown";
            return (
              <tr key={h.id}>
                <td>{h.enabled ? "yes" : "no"}</td>
                <td>
                  {h.url ? (
                    <a href={h.url} target="_blank" rel="noreferrer">
                      {h.name || h.id}
                    </a>
                  ) : (
                    h.name || h.id
                  )}
                </td>
                <td>{h.ipaddr}</td>
                <td>{label}</td>
                <td className="actions-cell">
                  <div className="actions">
                  <button type="button" className="sm btn-action" onClick={() => setEditing({ ...h })}>
                    Edit
                  </button>
                  <button
                    type="button"
                    className="sm"
                    disabled={disabled}
                    onClick={async () => {
                      const r = await apiGet<{ activity: ActivityPoint[] }>(
                        `/api/v1/hosts/${encodeURIComponent(h.id)}/activity`,
                      );
                      setModal(
                        <div>
                          <h3>Activity ({h.name})</h3>
                          <p style={{ fontSize: "0.85rem", color: "#666" }}>
                            Hourly reachability (1=recent poll OK).
                          </p>
                          <table>
                            <tbody>
                              {r.activity.slice(-48).map((a) => (
                                <tr key={a.timestamp}>
                                  <td>{new Date(a.timestamp * 1000).toLocaleString()}</td>
                                  <td>{a.value}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <button type="button" onClick={() => setModal(null)}>
                            Close
                          </button>
                        </div>,
                      );
                    }}
                  >
                    Activity
                  </button>
                  <button
                    type="button"
                    className="sm"
                    disabled={disabled}
                    onClick={async () => {
                      setModal(
                        <div>
                          <h3>Ping {h.ipaddr}</h3>
                          <div className="ping-loading">
                            <span className="throbber" />
                            Pinging&hellip;
                          </div>
                          <button type="button" onClick={() => setModal(null)}>
                            Close
                          </button>
                        </div>,
                      );
                      const r = await apiPostJson<{ stdout: string; stderr: string; code: number }>(
                        `/api/v1/hosts/${encodeURIComponent(h.id)}/ping`,
                      );
                      setModal(
                        <div>
                          <h3>Ping {h.ipaddr}</h3>
                          <pre style={{ whiteSpace: "pre-wrap" }}>{r.stdout || r.stderr}</pre>
                          <button type="button" onClick={() => setModal(null)}>
                            Close
                          </button>
                        </div>,
                      );
                    }}
                  >
                    Ping
                  </button>
                  <button
                    type="button"
                    className="sm"
                    disabled={disabled}
                    onClick={async () => {
                      const scr = await apiGet<{ scripts: { file: string; description: string; warn: number }[] }>(
                        "/api/v1/scripts",
                      );
                      setModal(
                        <ScriptPicker
                          hostId={h.id}
                          scripts={scr.scripts}
                          onClose={() => setModal(null)}
                        />,
                      );
                    }}
                  >
                    Script
                  </button>
                  <button
                    type="button"
                    className="sm btn-remove"
                    onClick={() =>
                      void onSave({ ...cfg, hosts: cfg.hosts.filter((x) => x.id !== h.id) })
                    }
                  >
                    Delete
                  </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3 style={{ marginTop: "1.5rem" }}>Wireless clients</h3>
      <table>
        <thead>
          <tr>
            {clientCols.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {clients.length === 0 ? (
            <tr>
              <td colSpan={Math.max(1, clientCols.length)}>No clients</td>
            </tr>
          ) : (
            clients.map(({ ap, band, c }, i) => (
              <tr key={i}>
                {clientCols.map((col) => (
                  <td key={col}>{formatClientCell(col, ap, band, c)}</td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>

      {editing && (
        <HostEditor
          host={editing}
          onChange={setEditing}
          onClose={() => setEditing(null)}
          onSubmit={async () => {
            const hosts = cfg.hosts.some((x) => x.id === editing.id)
              ? cfg.hosts.map((x) => (x.id === editing.id ? editing : x))
              : [...cfg.hosts, editing];
            await onSave({ ...cfg, hosts });
            setEditing(null);
          }}
        />
      )}
    </section>
  );
}

function formatClientCell(col: string, ap: string, band: number, c: ClientRow): string {
  switch (col) {
    case "ap":
      return ap;
    case "band":
      return band === 2 ? "2.4 GHz" : band === 5 ? "5 GHz" : "6 GHz";
    case "wifi":
      return c.wifi > 0 ? `Wi-Fi ${c.wifi}` : "-";
    case "signal":
      return c.signal != null ? `${c.signal} dBm` : "-";
    default:
      return String((c as Record<string, unknown>)[col] ?? "-");
  }
}

function ScriptPicker({
  hostId,
  scripts,
  onClose,
}: {
  hostId: string;
  scripts: { file: string; description: string; warn: number }[];
  onClose: () => void;
}) {
  const [sel, setSel] = useState(scripts[0]?.file ?? "");
  const [out, setOut] = useState("");
  const [eout, setEout] = useState("");
  return (
    <div>
      <h3>Run script</h3>
      <select value={sel} onChange={(e) => setSel(e.target.value)}>
        {scripts.map((s) => (
          <option key={s.file} value={s.file}>
            {s.description}
          </option>
        ))}
      </select>
      <div className="actions" style={{ marginTop: "0.5rem" }}>
        <button
          type="button"
          className="btn-action"
          onClick={async () => {
            const sc = scripts.find((s) => s.file === sel);
            if (sc?.warn && !window.confirm(`Run “${sc.description}”?`)) return;
            const r = await apiPostJson<{ stdout: string; stderr: string }>(
              `/api/v1/hosts/${encodeURIComponent(hostId)}/scripts/${encodeURIComponent(sel)}/run`,
            );
            setOut(r.stdout);
            setEout(r.stderr);
          }}
        >
          Execute
        </button>
      </div>
      <label>stdout</label>
      <textarea className="mono" readOnly value={out} rows={8} />
      <label>stderr</label>
      <textarea className="mono" readOnly value={eout} rows={4} />
      <button type="button" onClick={onClose}>
        Close
      </button>
    </div>
  );
}

function HostEditor({
  host,
  onChange,
  onClose,
  onSubmit,
}: {
  host: Host;
  onChange: (h: Host) => void;
  onClose: () => void;
  onSubmit: () => Promise<void>;
}) {
  return (
    <div className="row-editor">
      <h4>Edit device</h4>
      <label>Name</label>
      <input
        type="text"
        value={host.name}
        onChange={(e) => onChange({ ...host, name: e.target.value })}
      />
      <label>IP / hostname</label>
      <input
        type="text"
        value={host.ipaddr}
        onChange={(e) => onChange({ ...host, ipaddr: e.target.value })}
      />
      <label>Port</label>
      <input
        type="number"
        value={host.port}
        onChange={(e) => onChange({ ...host, port: Number(e.target.value) || 22 })}
      />
      <label>Username</label>
      <input
        type="text"
        value={host.username}
        onChange={(e) => onChange({ ...host, username: e.target.value })}
      />
      <label>
        <input
          type="checkbox"
          checked={host.usekeyfile}
          onChange={(e) => onChange({ ...host, usekeyfile: e.target.checked })}
        />{" "}
        SSH key
      </label>
      {host.usekeyfile ? (
        <>
          <label>Key file path</label>
          <input
            type="text"
            value={host.keyfile}
            onChange={(e) => onChange({ ...host, keyfile: e.target.value })}
          />
        </>
      ) : (
        <>
          <label>Password</label>
          <input
            type="password"
            value={host.password}
            onChange={(e) => onChange({ ...host, password: e.target.value })}
          />
        </>
      )}
      <label>GUI URL</label>
      <input
        type="text"
        value={host.url}
        placeholder="https://..."
        onChange={(e) => onChange({ ...host, url: e.target.value })}
      />
      <label>Trunk / uplink port</label>
      <input
        type="text"
        value={host.trunk_port}
        placeholder="e.g. lan1 (required for tagged VLANs)"
        onChange={(e) => onChange({ ...host, trunk_port: e.target.value })}
      />
      <label>Management VLAN (untagged)</label>
      <input
        type="number"
        min={1}
        max={4094}
        value={host.mgmt_vlan}
        onChange={(e) => onChange({ ...host, mgmt_vlan: Number(e.target.value) || 1 })}
      />
      <label>
        <input
          type="checkbox"
          checked={host.dumb_ap ?? true}
          onChange={(e) => onChange({ ...host, dumb_ap: e.target.checked })}
        />{" "}
        Dumb AP Mode (disables dnsmasq, odhcpd, and firewall)
      </label>
      <label>
        <input
          type="checkbox"
          checked={host.enabled}
          onChange={(e) => onChange({ ...host, enabled: e.target.checked })}
        />{" "}
        Enabled (polled periodically)
      </label>
      <div className="actions" style={{ marginTop: 8 }}>
        <button type="button" className="btn-positive" onClick={() => void onSubmit()}>
          Save device
        </button>
        <button type="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function WifiTab({ cfg, onSave }: { cfg: RootConfig; onSave: (c: RootConfig) => Promise<void> }) {
  const [editing, setEditing] = useState<Wifi | null>(null);
  return (
    <section>
      <button
        type="button"
        className="btn-positive"
        onClick={() => {
          const w: Wifi = {
            id: nextWifiId(cfg.wifis),
            name: "",
            enabled: true,
            band: ["2g", "5g"],
            ssid: "",
            encryption: "psk2",
            key: "",
            hidden: false,
            isolate: false,
            network: "lan",
            vlan: "",
          };
          setEditing(w);
        }}
      >
        Add Wi-Fi
      </button>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>SSID</th>
            <th>Bands</th>
            <th>Network</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {cfg.wifis.map((w) => (
            <tr key={w.id}>
              <td>{w.name}</td>
              <td>{w.ssid}</td>
              <td>{w.band.join(", ")}</td>
              <td>
                {w.vlan
                  ? (() => {
                      const v = cfg.vlans.find((x) => x.id === w.vlan);
                      return v ? `${v.name || v.id} (VLAN ${v.vlan_id})` : `${w.vlan} (?)`;
                    })()
                  : `${w.network} (untagged)`}
              </td>
              <td>
                <button type="button" className="sm btn-action" onClick={() => setEditing({ ...w })}>
                  Edit
                </button>
                <button
                  type="button"
                  className="sm btn-remove"
                  onClick={() => void onSave({ ...cfg, wifis: cfg.wifis.filter((x) => x.id !== w.id) })}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing && (
        <div className="row-editor">
          <h4>Wi-Fi</h4>
          <label>Name</label>
          <input
            type="text"
            value={editing.name}
            onChange={(e) => setEditing({ ...editing, name: e.target.value })}
          />
          <label>SSID</label>
          <input
            type="text"
            value={editing.ssid}
            onChange={(e) => setEditing({ ...editing, ssid: e.target.value })}
          />
          <label>Bands</label>
          {(["2g", "5g", "6g"] as const).map((b) => (
            <label key={b}>
              <input
                type="checkbox"
                checked={editing.band.includes(b)}
                onChange={(e) => {
                  const on = e.target.checked;
                  setEditing({
                    ...editing,
                    band: on ? [...editing.band, b] : editing.band.filter((x) => x !== b),
                  });
                }}
              />{" "}
              {b}
            </label>
          ))}
          <label>Encryption</label>
          <select
            value={editing.encryption}
            onChange={(e) => setEditing({ ...editing, encryption: e.target.value })}
          >
            {ENCRYPTIONS.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
          <label>Key</label>
          <input
            type="password"
            value={editing.key}
            onChange={(e) => setEditing({ ...editing, key: e.target.value })}
          />
          <label>
            <input
              type="checkbox"
              checked={editing.enabled}
              onChange={(e) => setEditing({ ...editing, enabled: e.target.checked })}
            />{" "}
            Enabled
          </label>
          <label>
            <input
              type="checkbox"
              checked={editing.hidden}
              onChange={(e) => setEditing({ ...editing, hidden: e.target.checked })}
            />{" "}
            Hidden SSID
          </label>
          <label>
            <input
              type="checkbox"
              checked={editing.isolate}
              onChange={(e) => setEditing({ ...editing, isolate: e.target.checked })}
            />{" "}
            Isolate clients
          </label>
          <label>Network</label>
          <select
            value={editing.vlan}
            onChange={(e) => setEditing({ ...editing, vlan: e.target.value })}
          >
            <option value="">Management (untagged)</option>
            {cfg.vlans.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name || v.id} (VLAN {v.vlan_id})
              </option>
            ))}
          </select>
          {editing.vlan === "" && (
            <>
              <label>Management interface (UCI iface)</label>
              <input
                type="text"
                value={editing.network}
                onChange={(e) => setEditing({ ...editing, network: e.target.value })}
              />
            </>
          )}
          <div className="actions">
            <button
              type="button"
              className="btn-positive"
              onClick={() => {
                const exists = cfg.wifis.some((x) => x.id === editing.id);
                const wifis = exists
                  ? cfg.wifis.map((x) => (x.id === editing.id ? editing : x))
                  : [...cfg.wifis, editing];
                void onSave({ ...cfg, wifis });
                setEditing(null);
              }}
            >
              Save
            </button>
            <button type="button" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function VlansTab({ cfg, onSave }: { cfg: RootConfig; onSave: (c: RootConfig) => Promise<void> }) {
  const [editing, setEditing] = useState<Vlan | null>(null);
  return (
    <section>
      <p className="hint">
        VLANs are provisioned on the bridge of each managed AP using the device's trunk/uplink
        port (set per device on the Devices tab). The untagged management VLAN stays reachable on
        every port. Map an SSID to a VLAN from the Wi-Fi tab.
      </p>
      <button
        type="button"
        className="btn-positive"
        onClick={() => {
          const v: Vlan = {
            id: nextVlanId(cfg.vlans),
            name: "",
            vlan_id: 10,
            device: "br-lan",
          };
          setEditing(v);
        }}
      >
        Add VLAN
      </button>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>VLAN ID</th>
            <th>Bridge device</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {cfg.vlans.map((v) => (
            <tr key={v.id}>
              <td>{v.name || v.id}</td>
              <td>{v.vlan_id}</td>
              <td>{v.device}</td>
              <td>
                <button type="button" className="sm btn-action" onClick={() => setEditing({ ...v })}>
                  Edit
                </button>
                <button
                  type="button"
                  className="sm btn-remove"
                  onClick={() => {
                    const vlans = cfg.vlans.filter((x) => x.id !== v.id);
                    // Detach any SSIDs that referenced this VLAN.
                    const wifis = cfg.wifis.map((w) => (w.vlan === v.id ? { ...w, vlan: "" } : w));
                    void onSave({ ...cfg, vlans, wifis });
                  }}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing && (
        <div className="row-editor">
          <h4>VLAN</h4>
          <label>Name</label>
          <input
            type="text"
            value={editing.name}
            placeholder="e.g. Guest"
            onChange={(e) => setEditing({ ...editing, name: e.target.value })}
          />
          <label>VLAN ID (802.1q tag)</label>
          <input
            type="number"
            min={1}
            max={4094}
            value={editing.vlan_id}
            onChange={(e) => setEditing({ ...editing, vlan_id: Number(e.target.value) || 1 })}
          />
          <label>Bridge device</label>
          <input
            type="text"
            value={editing.device}
            onChange={(e) => setEditing({ ...editing, device: e.target.value })}
          />
          <div className="actions">
            <button
              type="button"
              className="btn-positive"
              onClick={() => {
                const exists = cfg.vlans.some((x) => x.id === editing.id);
                const vlans = exists
                  ? cfg.vlans.map((x) => (x.id === editing.id ? editing : x))
                  : [...cfg.vlans, editing];
                void onSave({ ...cfg, vlans });
                setEditing(null);
              }}
            >
              Save
            </button>
            <button type="button" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function GroupsTab({
  cfg,
  onSave,
  setModal,
}: {
  cfg: RootConfig;
  onSave: (c: RootConfig) => Promise<void>;
  setModal: (n: React.ReactNode) => void;
}) {
  const [editing, setEditing] = useState<Group | null>(null);
  return (
    <section>
      <button
        type="button"
        className="btn-positive"
        onClick={() =>
          setEditing({
            id: nextGroupId(cfg.groups),
            name: "",
            host: [],
            wifi: [],
            delete: false,
            useadditionalscript: false,
          })
        }
      >
        Add group
      </button>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Devices</th>
            <th>Wi-Fi</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {cfg.groups.map((g) => (
            <tr key={g.id}>
              <td>{g.name}</td>
              <td>{g.host.join(", ")}</td>
              <td>
                {g.wifi.map((id) => {
                  const w = cfg.wifis.find((x) => x.id === id);
                  return <div key={id}>{w ? w.name || w.ssid || id : id}</div>;
                })}
              </td>
              <td className="actions-cell">
                <div className="actions">
                <button type="button" className="sm btn-action" onClick={() => setEditing({ ...g })}>
                  Edit
                </button>
                <button
                  type="button"
                  className="sm btn-action"
                  onClick={async () => {
                    setModal(
                      <div>
                        <h3>Deploy</h3>
                        <div className="ping-loading">
                          <span className="throbber" />
                          Sending config&hellip;
                        </div>
                      </div>,
                    );
                    await onSave(cfg);
                    const r = await apiPostJson<{ stdout: string; stderr: string }>(
                      `/api/v1/groups/${encodeURIComponent(g.id)}/deploy?verbose=true`,
                    );
                    setModal(
                      <div>
                        <h3>Deploy</h3>
                        <pre>{r.stdout}</pre>
                        <button type="button" onClick={() => setModal(null)}>
                          Close
                        </button>
                      </div>,
                    );
                  }}
                >
                  Send
                </button>
                <button
                  type="button"
                  className="sm btn-remove"
                  onClick={() => void onSave({ ...cfg, groups: cfg.groups.filter((x) => x.id !== g.id) })}
                >
                  Delete
                </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing && (
        <div className="row-editor">
          <h4>AP Group</h4>
          <label>Name</label>
          <input
            type="text"
            value={editing.name}
            onChange={(e) => setEditing({ ...editing, name: e.target.value })}
          />
          <label>Devices</label>
          {cfg.hosts.map((h) => (
            <label key={h.id}>
              <input
                type="checkbox"
                checked={editing.host.includes(h.id)}
                onChange={(e) => {
                  const on = e.target.checked;
                  setEditing({
                    ...editing,
                    host: on
                      ? [...editing.host, h.id]
                      : editing.host.filter((x) => x !== h.id),
                  });
                }}
              />{" "}
              {h.name} ({h.ipaddr})
            </label>
          ))}
          <label>Wi-Fi profiles</label>
          {cfg.wifis.map((w) => (
            <label key={w.id}>
              <input
                type="checkbox"
                checked={editing.wifi.includes(w.id)}
                onChange={(e) => {
                  const on = e.target.checked;
                  setEditing({
                    ...editing,
                    wifi: on
                      ? [...editing.wifi, w.id]
                      : editing.wifi.filter((x) => x !== w.id),
                  });
                }}
              />{" "}
              {w.name || w.ssid}
            </label>
          ))}
          <label>
            <input
              type="checkbox"
              checked={editing.delete}
              onChange={(e) => setEditing({ ...editing, delete: e.target.checked })}
            />{" "}
            Delete all Wi-Fi on device before apply
          </label>
          <label>
            <input
              type="checkbox"
              checked={editing.useadditionalscript}
              onChange={(e) => setEditing({ ...editing, useadditionalscript: e.target.checked })}
            />{" "}
            Run additional script (Settings tab) before Wi-Fi changes
          </label>
          <div className="actions">
            <button
              type="button"
              className="btn-positive"
              onClick={() => {
                const exists = cfg.groups.some((x) => x.id === editing.id);
                const groups = exists
                  ? cfg.groups.map((x) => (x.id === editing.id ? editing : x))
                  : [...cfg.groups, editing];
                void onSave({ ...cfg, groups });
                setEditing(null);
              }}
            >
              Save group
            </button>
            <button type="button" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function SettingsTab({
  cfg,
  onSave,
  onReloadScript,
}: {
  cfg: RootConfig;
  onSave: (c: RootConfig) => Promise<void>;
  onReloadScript: () => Promise<void>;
}) {
  const [g, setG] = useState<GlobalSection>(cfg.global);
  const [script, setScript] = useState(cfg.additional_script);

  useEffect(() => {
    setG(cfg.global);
    setScript(cfg.additional_script);
  }, [cfg]);

  const DEVICE_COLS = [
    "enabled",
    "name",
    "ipaddr",
    "lastcontact",
    "mac",
    "hostname",
    "model",
    "software",
    "uptime",
    "load",
    "clients2g",
    "clients5g",
    "clients6g",
    "channels2g",
    "channels5g",
    "channels6g",
  ];
  const CLIENT_COLS = [
    "ap",
    "ssid",
    "name",
    "mac",
    "ipaddr",
    "band",
    "wifi",
    "signal",
    "connected",
    "rx",
    "tx",
  ];

  return (
    <section>
      <label>Data directory (status cache)</label>
      <input type="text" value={g.path} onChange={(e) => setG({ ...g, path: e.target.value })} />
      <label>Poll interval (minutes)</label>
      <input
        type="number"
        min={1}
        value={g.interval}
        onChange={(e) => setG({ ...g, interval: Number(e.target.value) || 1 })}
      />
      <h4>Device table columns</h4>
      {DEVICE_COLS.map((c) => (
        <label key={c}>
          <input
            type="checkbox"
            checked={g.column.includes(c)}
            onChange={(e) => {
              const on = e.target.checked;
              setG({
                ...g,
                column: on ? [...g.column, c] : g.column.filter((x) => x !== c),
              });
            }}
          />{" "}
          {c}
        </label>
      ))}
      <h4>Client table columns</h4>
      {CLIENT_COLS.map((c) => (
        <label key={c}>
          <input
            type="checkbox"
            checked={g.clientcolumn.includes(c)}
            onChange={(e) => {
              const on = e.target.checked;
              setG({
                ...g,
                clientcolumn: on ? [...g.clientcolumn, c] : g.clientcolumn.filter((x) => x !== c),
              });
            }}
          />{" "}
          {c}
        </label>
      ))}
      <h4>Additional shell script (per Wi-Fi variables: $_ENABLED, $_SSID, $_BAND, $_NETWORK)</h4>
      <textarea
        className="mono"
        value={script}
        onChange={(e) => setScript(e.target.value)}
        rows={12}
      />
      <div className="actions">
        <button
          type="button"
          className="btn-positive"
          onClick={() => void onSave({ ...cfg, global: g, additional_script: script })}
        >
          Save settings and script
        </button>
        <button type="button" onClick={() => void onReloadScript()}>
          Reload script from server
        </button>
      </div>
    </section>
  );
}
