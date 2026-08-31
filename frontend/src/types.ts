export interface GlobalSection {
  interval: number;
  path: string;
  column: string[];
  clientcolumn: string[];
}

export interface Host {
  id: string;
  enabled: boolean;
  name: string;
  ipaddr: string;
  port: number;
  username: string;
  password: string;
  usekeyfile: boolean;
  keyfile: string;
  url: string;
  trunk_port: string;
  mgmt_vlan: number;
  dumb_ap: boolean;
}

export interface Vlan {
  id: string;
  name: string;
  vlan_id: number;
  device: string;
}

export interface Wifi {
  id: string;
  name: string;
  enabled: boolean;
  band: string[];
  ssid: string;
  encryption: string;
  key: string;
  hidden: boolean;
  isolate: boolean;
  network: string;
  vlan: string;
}

export interface Group {
  id: string;
  name: string;
  host: string[];
  wifi: string[];
  delete: boolean;
  useadditionalscript: boolean;
}

export interface RootConfig {
  global: GlobalSection;
  hosts: Host[];
  wifis: Wifi[];
  vlans: Vlan[];
  groups: Group[];
  additional_script: string;
}

export interface StatusHost {
  section: string;
  enabled: boolean;
  name: string;
  ipaddr: string;
  port: number;
  username: string;
  password: string;
  lastcontact: number;
  hostname?: string;
  model?: string;
  load?: string;
  uptime?: number;
  mac?: string;
  software?: string;
  channels2g?: string;
  channels5g?: string;
  channels6g?: string;
  clientslist2g?: ClientRow[];
  clientslist5g?: ClientRow[];
  clientslist6g?: ClientRow[];
}

export interface ClientRow {
  ssid: string;
  mac: string;
  rx: number;
  tx: number;
  signal: number;
  connected: number;
  wifi: number;
  ipaddr: string;
  name: string;
}

export interface ActivityPoint {
  timestamp: number;
  value: number;
}
