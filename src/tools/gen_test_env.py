# SimpleEdgeGatewayお試し環境定義データ作成ツール
# 動作させるにはSimplePLCSimが別途必要となります。
# https://github.com/pekokana/SimplePLCSim/releases/tag/v0.1.0
import yaml
import os

# 実行時コマンド例
# uv run python -m src.tools.gen_test_env

# 独自のDumperを作成（インデント設定を強制するため）
class MyDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        # indentless=False にすることで、リストのハイフンを強制的にインデントさせる
        return super(MyDumper, self).increase_indent(flow, indentless=False)

# 基本設定
BASE_DIR = "D:/dev/SimpleEdgeGateway/opttools/large"
EXE_DIR = "D:/dev/SimpleEdgeGateway/opttools"
APP_SETTINGS = {
    "plc": {
        "exename": "plcsim.exe",
        "version": "1.0",
        "name": "plc_dummy_",
        "scan_cycle_ms": 100,
        "mem_X": 100,
        "mem_Y": 100,
        "mem_M": 100,
        "mem_D": 100
    },
    "ladder": {
        "version": "1.0",
        "name": "ladder_dummy_",
    },
    "device": {
        "exename": "devicesim.exe",
        "version": "1.0",
        "name": "device_dummy_",
        "heartbeat_offset": 512,
        "cycle_ms": 100
    },
    "orchestrator": {
        "exename": "orchestrator.exe",
        "version": "1.0",
        "name": "orchestrator"
    }
}

## PLC
PLC_MAKE_COUNT = 4
PLC_START_PORT = 15001
PLC_EDGE_PER_PLC = 100

## Ladder
### 特にない

## Device
DEV_MAKE_COUNT = 4
DEV_PLC_DI_START_ADDR = 0

## IODevice
### 今回は使わない

## yaml定義生成

def gen_yaml():
    ## 1. PLC生成
    memX = APP_SETTINGS['plc']["mem_X"]
    memY = APP_SETTINGS['plc']["mem_Y"]
    memM = APP_SETTINGS['plc']["mem_M"]
    memD = APP_SETTINGS['plc']["mem_D"]

    for p in range(1, PLC_MAKE_COUNT + 1):
        port = PLC_START_PORT + p -1
        plc_yaml_name = f"{APP_SETTINGS["plc"]["name"]}{p}.yaml"
        
        plc_data = {
            "kind": "plc",
            "version": APP_SETTINGS["plc"]["version"],
            "name": f"{APP_SETTINGS["plc"]["name"]}{p}",
            "log_dir" : f"{BASE_DIR}/logs",
            "power": True,
            "cpu": { "scan_cycle_ms": APP_SETTINGS["plc"]["scan_cycle_ms"] },
            "memory": { "X": memX, "Y": memY, "M": memM, "D": memD},
            "modbus": { "port": port}
        }
        with open(os.path.join(BASE_DIR, plc_yaml_name), "w", encoding="utf-8") as f:
                yaml.dump(plc_data, f, allow_unicode=True, sort_keys=False)

    ## 2. Ladder生成
    for p in range(1, PLC_MAKE_COUNT + 1):
        ladder_yaml_name = f"{APP_SETTINGS["ladder"]["name"]}{p}.yaml"
        port = PLC_START_PORT + p -1

        ladder_rungs = []

        for lmx in range(0, 4):
            ladder_rungs.append(f"""[ X{lmx} ] --(D{lmx} = D{lmx} + 1)""")
            ladder_rungs.append(f"""[ D{lmx} > 1000 ] --(D{lmx} = 0)""")
            ladder_rungs.append(f"""[ D{lmx} > 500 ] --(M{lmx})""")
        ladder_rungs.append(f"""END""")

        ladder_data = {
            "kind": "ladder",
            "version": APP_SETTINGS["ladder"]["version"],
            "rungs": ladder_rungs
        }
        with open(os.path.join(BASE_DIR, ladder_yaml_name), "w", encoding="utf-8") as f:
                yaml.dump(
                     ladder_data, 
                     f,
                     Dumper=MyDumper,
                     allow_unicode=True, 
                     sort_keys=False, 
                     default_style='"', 
                     indent=2
                )

    ## 3. Device生成

    for p in range(1, DEV_MAKE_COUNT + 1):
        port = PLC_START_PORT + p -1

        # シグナル定義の作成
        dev_signal = {}

        for lmx in range(0, 4):
            # 2. パターンを毎回新しく作成する（参照コピーによる &id001 発生を防ぐ）
            # valueはbool型(True/False)にすると、YAMLで true/false になります
            current_pattern = [
                { "value": True, "duration_ms": 5000 },
                { "value": False, "duration_ms": 5000 }
            ]

            # 辞書への動的追加: dev_signal["キー名"] = 値
            dev_signal[f"upstream{lmx}"] = {
                "type": "discrete",
                "address": DEV_PLC_DI_START_ADDR + lmx,
                "pattern": current_pattern
            }


        device_yaml_name = f"{APP_SETTINGS["device"]["name"]}{p}.yaml"

        dev_data = {
            "kind": "device",
            "version": APP_SETTINGS["device"]["version"],
            "device": {
                "name": f"{APP_SETTINGS["device"]["name"]}{p}",
                "log_dir" : f"{BASE_DIR}/logs",
                "plc": {
                     "host": "localhost",
                     "port": port,
                     "heartbeat_offset": APP_SETTINGS['device']["heartbeat_offset"]
                },
                "cycle_ms": APP_SETTINGS['device']['cycle_ms'],
                "signals": dev_signal
            }
        }

        with open(os.path.join(BASE_DIR, device_yaml_name), "w", encoding="utf-8") as f:
                yaml.dump(
                     dev_data, 
                     f,
                     Dumper=MyDumper,
                     allow_unicode=True, 
                     sort_keys=False, 
                    #  default_style='"', 
                     indent=2
                )

    ## 4. IODevice生成
    ### 今回は使わない

    ## 5. Orchestrator生成

    # サービスリストの初期化
    orch_services = []

    for p in range(1, PLC_MAKE_COUNT + 1):
        # 変数の準備
        port = PLC_START_PORT + p - 1
        plc_name = f"plc_dummy{p}"
        dev_name = f"dev_dummy{p}"
        
        plc_yaml = f"{APP_SETTINGS["plc"]["name"]}{p}.yaml"
        ladder_yaml = f"{APP_SETTINGS["ladder"]["name"]}{p}.yaml"
        device_yaml = f"{APP_SETTINGS["device"]["name"]}{p}.yaml"

        # 1. PLCサービスの定義を追加
        orch_services.append({
            "name": plc_name,
            "type": "plc",
            "command": [f"{EXE_DIR}/plcsim.exe"],
            "args": [f"{BASE_DIR}/{plc_yaml}", f"{BASE_DIR}/{ladder_yaml}"],
            "ready_check": {
                "kind": "modbus",
                "host": "127.0.0.1",
                "port": port
            }
        })

        # 2. Deviceサービスの定義を追加
        orch_services.append({
            "name": dev_name,
            "type": "device",
            "command": [f"{EXE_DIR}/devicesim.exe"],
            "args": [f"{BASE_DIR}/{device_yaml}"],
            "depends_on": [plc_name] # 先ほど定義したPLC名に依存させる
        })

    # 全体の構造作成
    orch_data = {
        "kind": "orchestrator",
        "version": "1.0",
        "log": {
            "dir": f"{BASE_DIR}/logs"
        },
        "services": orch_services
    }

    # YAMLファイルへの書き出し
    orch_yaml_path = os.path.join(BASE_DIR, "orchestrator.yaml")
    with open(orch_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(
            orch_data, 
            f, 
            Dumper=MyDumper,      # 前回作成したインデント対応Dumper
            allow_unicode=True, 
            sort_keys=False, 
            indent=2
        )



    ## 6. EdgeServerインポートyaml生成
    edge_hosts = []

    for p in range(1, PLC_MAKE_COUNT + 1):
        port = PLC_START_PORT + p - 1
        items = []

        # 1台のPLCにつき指定された数（PLC_EDGE_PER_PLC）の監視アイテムを生成
        for i in range(PLC_EDGE_PER_PLC):
            # 最後の1つはHeartbeat(512)にする、それ以外はD0, D1...とする例
            if i == PLC_EDGE_PER_PLC - 1:
                tag_addr = APP_SETTINGS["device"]["heartbeat_offset"]
                tag_name = f"P{p}_SYS_Heartbeat"
            else:
                tag_addr = i
                tag_name = f"P{p}_DATA_{i:03d}"

            items.append({
                "tag_name": tag_name,
                "address": tag_addr,
                "alarm_threshold": 800.0,  # ラダーで1000リセットなので800を閾値に
                "alarm_enabled": True,     # 負荷軽減のためデフォルトOFF
                "polling_interval": 1       # 1秒周期
            })

        # ホスト情報の構築
        edge_hosts.append({
            "display_name": f"LARGE_PLC_{p:02d}",
            "ip_address": "127.0.0.1",
            "port": port,
            "unit_id": 1,
            "is_active": True,
            "items": items
        })

    # インポート用データの全体構造
    edge_import_data = {
        "hosts": edge_hosts
    }

    # ファイル書き出し
    edge_yaml_path = os.path.join(BASE_DIR, "edge_import_large.yaml")
    with open(edge_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(
            edge_import_data,
            f,
            Dumper=MyDumper,
            allow_unicode=True,
            sort_keys=False,
            indent=2
        )

    ## 7. 後処理(あれば)


    ## 7. 後処理(あれば)
    print(f"完了! {BASE_DIR} に大規模検証用ファイルを生成しました。")

if __name__ == "__main__":
    gen_yaml()