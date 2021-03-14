import json
import os
import re
from decimal import Decimal
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib import hub
from ryu.controller import dpset
from webob import Response

from operator import attrgetter

from py2neo import Graph, Node, Relationship

from definitions.host import HOST_LIST
from definitions.network import LINK

from enum import Enum

# neo4jのdatabaseのパスワードを環境変数から取得
DB_PASS = os.getenv("DB_PASS", "password")

# rest api用のインスタンスとurl
controller_instance_name = 'controller_api_app'
video_url = '/controller/video/flowtable'
other_traffic_url = '/controller/other/flowtable'
get_other_traffic = '/controller/other/flowtable'
other_traffic_complete_url = '/controller/other/complete'

# ビデオストリームと他トラフィックの最低保障帯域（ＭＢ）
LIMIT_VIDEO_BANDWIDTH = 20
LIMIT_OTHER_BANDWIDTH = 20

class PathSelectAlgorithm(Enum):
    '''
    切り替えアルゴリズム用Enumクラス
    '''
    NO_CHANGE: int = 0
    SHORTEST_PATH: int = 1
    LONGEST_PATH: int = 2
    BANDWIDTH: int = 3
 
PATH_SELECT_ALGORITHM = PathSelectAlgorithm.BANDWIDTH

class OpenflowController(app_manager.RyuApp):
    '''
    RYUのコントローラークラス
    '''
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
        'dpset': dpset.DPSet,
        'wsgi': WSGIApplication
    }

    def __init__(self, *args, **kwargs):
        '''
        初期化
        '''
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.stats_info = {}
        self.dpset = kwargs['dpset']
        self.graph = Graph(password=DB_PASS)
        self.monitor_thread = hub.spawn(self._monitor)
        self.other_traffic = {}
        self.flow_stats_info = {}
        self.other_traffic_rate = {}
        wsgi = kwargs['wsgi']
        wsgi.register(RestController,
                      {controller_instance_name: self})

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        '''
        openflowスイッチの初期設定
        各スイッチに最短パスのフローを登録する
        '''
        datapath = ev.msg.datapath
        self.stats_info[str(datapath.id)] = {}
        self.flow_stats_info[str(datapath.id)] = {}
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        self.__initial_setup_flow_table(datapath)

    def __get_shortest_path(self, src_type, src_node_name, dst_type, dst_node_name):
        '''
        neo4jからsrcとdst間の最短パスを取得する
        '''
        string = f'MATCH p = shortestPath((s:{src_type} {{name:"{src_node_name}"}})-[:connect*0..]-(d:{dst_type} {{name:"{dst_node_name}"}})) RETURN p'
        res = self.graph.run(string)
        lines = str(res).split("\n")
        return lines[2]

    def __get_connected_host(self, datapath_id):
        '''
        neo4jからdatapath_idに対応するスイッチに接続されているhostを取得する
        '''
        string = f'MATCH (s:switch {{name:"s{datapath_id}"}})-[:connect]->(d:host) RETURN d'
        res = self.graph.run(string)
        lines = str(res).split("\n")
        hosts = []
        for i in range(len(lines)):
            if i < 2:
                continue
            m = re.search(r'^ \([^ ]* {name: \'(.*)\'}\)', lines[i])
            print(lines[i])
            if m:
                hosts.append(m.group(1))
        
        return hosts

    def __initial_setup_flow_table(self, datapath):
        '''
        datapathに対応するスイッチに初期フロー（最短パス）を登録する
        '''
        switch_name = f"s{datapath.id}"
        parser = datapath.ofproto_parser
        for host in HOST_LIST:
            # スイッチからhostへの最短パスを取得
            shortest_path = self.__get_shortest_path("switch", switch_name, "host", host["name"])
            # 最短パスから次のnodeを取得し、そのnodeがつながるポートを取得
            m = re.search(r'^ \((s[\w]*)\)[^(]*\(([sh][\w]*)\).*', shortest_path)
            next_node_name = m.group(2)
            out_port = self.__get_ports(next_node_name, switch_name)
            # 各hostを送信元とするフローを登録
            actions = [parser.OFPActionOutput(int(out_port))]
            for src_host in HOST_LIST:
                if src_host == host:
                    continue
                match = parser.OFPMatch(eth_src=src_host["mac"], eth_dst=host["mac"])
                self.add_flow(datapath, 1, match, actions)
                
    def __get_ports(self, dst_node, switch):
        '''
        Switchのあるnodeがつながるportを取得
        '''
        for li in LINK:
            if li[0] == dst_node and li[2] == switch:
                out_port = li[3]
            elif li[2] == dst_node and li[0] == switch:
                out_port = li[1]
        return out_port

    def add_flow(self, datapath, priority, match, actions):
        '''
        datapathに対応するSwitchにフローを登録する
        '''
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # construct flow_mod message and send it.
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        pass

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        '''
        トラフィックをモニターするSwitchを登録/削除する
        '''
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.debug('register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]

    def _monitor(self):
        '''
        トラフィックをモニターする
        モニター間隔は10秒
        '''
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(10)

    def _request_stats(self, datapath):
        '''
        Switchに統計情報をリクエスト
        '''
        self.logger.debug('send stats request: %016x', datapath.id)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # フロー統計情報をリクエスト
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

        # ポート統計情報をリクエスト
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        '''
        Switchから受信したフロー統計情報の処理
        '''
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        for stat in body:
            if stat.priority != 1:
                raise Exception("stats monitor error")
            self.__update_flow_stats_info(dpid, stat)

    def __update_flow_stats_info(self, dpid, stat):
        '''
        フロー統計情報を元に以下をアップデート
        self.flow_stats_info：各Switchのフロー統計情報
        self.other_traffic_rate：他トラフィックの使用帯域情報
        '''
        src_mac = stat.match['eth_src']
        dst_mac = stat.match['eth_dst']
        src_host = list(filter(lambda x: x["mac"] == src_mac, HOST_LIST))[0]["name"]
        dst_host = list(filter(lambda x: x["mac"] == dst_mac, HOST_LIST))[0]["name"]
        duration_sec = stat.duration_sec
        duration_nsec = stat.duration_nsec
        tx_bytes = stat.byte_count
        flow_info = self.flow_stats_info.get(str(dpid), {}).get(f"{src_host}{dst_host}", {})
        sec = (stat.duration_sec + stat.duration_nsec / 10**9) - flow_info.get("duration", 0)
        tx_bytes_of_this_duration = tx_bytes - flow_info.get("tx_bytes", 0)
        tx_rate = tx_bytes_of_this_duration * 8 / sec
        # 各Switchのフロー統計情報を更新
        self.flow_stats_info[str(dpid)].update(
                {
                f"{src_host}{dst_host}": {
                    'duration': stat.duration_sec + stat.duration_nsec / 10**9,
                    'tx_bytes': tx_bytes
                }
            }
        )
        # self.other_trafficにデータがない場合は、現在発生しているトラフィックではないのでself.other_traffic_rateから情報を消す
        if not self.other_traffic.get(f"{src_host}{dst_host}"):
            self.other_traffic_rate.pop(f"{src_host}{dst_host}", None)
            return 
        # 他トラフィックの使用帯域情報を更新
        self.other_traffic_rate[f"{src_host}{dst_host}"] = {
            'tx_rate': tx_rate
        }

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        '''
        Switchから受信したポート統計情報の処理
        '''
        body = ev.msg.body
        dpid = ev.msg.datapath.id

        for stat in sorted(body, key=attrgetter('port_no')):
            # ポート統計情報の更新
            port_no, rx_rate, tx_rate = self.__update_stats_info(dpid, stat)
            # neo4jの情報を更新
            self.__update_bandwitdh_usage(switch_name=f's{dpid}', port=str(port_no), rx_rate=rx_rate, tx_rate=tx_rate)

    def __update_stats_info(self, dpid, stat):
        '''
        ポート統計情報を元に以下をアップデート
        self.stats_info：各Switchのポート統計情報
        '''
        port_no = stat.port_no
        duration_sec = stat.duration_sec
        duration_nsec = stat.duration_nsec
        rx_bytes = stat.rx_bytes
        tx_bytes = stat.tx_bytes
        port_info = self.stats_info.get(str(dpid), {}).get(str(port_no), {})
        sec = (stat.duration_sec + stat.duration_nsec / 10**9) - port_info.get("duration", 0)
        rx_bytes_of_this_duration = rx_bytes - port_info.get("rx_bytes", 0)
        tx_bytes_of_this_duration = tx_bytes - port_info.get("tx_bytes", 0)
        rx_rate = rx_bytes_of_this_duration * 8 / sec
        tx_rate = tx_bytes_of_this_duration * 8 / sec
        # 各Switchのポート統計情報を更新
        self.stats_info[str(dpid)].update(
                {
                str(port_no): {
                    'duration': stat.duration_sec + stat.duration_nsec / 10**9,
                    'rx_bytes': rx_bytes,
                    'tx_bytes': tx_bytes
                }
            }
        )
        return port_no, rx_rate, tx_rate

    def __update_bandwitdh_usage(self, switch_name, port, tx_rate, rx_rate):
        '''
        ポート統計情報を元にneo4jの情報をアップデート
        '''
        tx_rate_mb = tx_rate / 1024 / 1024
        rx_rate_mb = rx_rate / 1024 / 1024
        connected_node = None
        # Switchの該当ポートに接続されているnodeを検索
        for li in LINK:
            if li[0] == switch_name and li[1] == port:
                connected_node = li[2]
            elif li[2] == switch_name and li[3] == port:
                connected_node = li[0]

        # Switchの該当ポートに接続されているnodeがなければreturn
        if not connected_node:
            return

        # neo4jで管理している各リンクの使用帯域情報をアップデート
        if connected_node.startswith('s'):
            string = f'MATCH (s:switch {{name:"{switch_name}"}})-[c:connect]->(d:switch{{name:"{connected_node}"}}) SET c.{switch_name}{connected_node} = {tx_rate_mb}, c.{connected_node}{switch_name} = {rx_rate_mb} RETURN d'
        elif connected_node.startswith('h'):
            string = f'MATCH (s:switch {{name:"{switch_name}"}})-[c:connect]->(d:host{{name:"{connected_node}"}}) SET c.{switch_name}{connected_node} = {tx_rate_mb}, c.{connected_node}{switch_name} = {rx_rate_mb} RETURN d'
        else:
            raise Exception('Internal Error')
        self.graph.run(string)

    def update_flow_table(self, src_host, dst_host, traffic_type):
        '''
        シミュレーションのスクリプトからフローアップデートをリクエストされた時に実行されるメソッド
        '''
        # ビデオトラフィックの場合の処理
        if traffic_type == "video":
            # src_hostからdst_hostへの最短パスを取得
            path_list = [self.__get_shortest_path("host", src_host, "host", dst_host)]
            path_info_list = self.__parse_path_list(path_list)
            # フローをアップデート
            self.__update_video_flow_table(path_info_list)
        # 他トラフィックの場合の処理
        else:
            # src_hostからdst_hostへの全パスを取得
            path_list = self.__get_path_list("host", src_host, "host", dst_host)
            path_info_list = self.__parse_path_list(path_list)
            #フローをアップデート
            self.__update_other_flow_table(path_info_list)
        
    def __get_path_list(self, src_type, src_node_name, dst_type, dst_node_name, filter_path = None):
        '''
        src_node_nameからdst_node_nameへのパス情報を取得する
        filter_pathに含まれるパスは含まない
        '''
        total_paths = []
        where_string = ""
        # filter_pathが含まれる場合はfilter条件を追加
        if filter_path:
            where_string = "WHERE ALL(n IN RELATIONSHIPS(p) WHERE not "
            for i in range(len(filter_path) - 1):
                where_string += f'(startNode(n).name = "{filter_path[i]}" and endNode(n).name = "{filter_path[i + 1]}") and not '
                where_string += f'(startNode(n).name = "{filter_path[i + 1]}" and endNode(n).name = "{filter_path[i]}") and not '
            where_string = where_string[:-9] + ") "
        # ホップ数が20までの経路を取得
        for i in range(20):
            string = f'MATCH p = (h:{src_type} {{name:"{src_node_name}"}})-[:connect*{i}..{i}]-(d:{dst_type} {{name:"{dst_node_name}"}}) {where_string}RETURN p'
            res = self.graph.run(string)
            paths = str(res).split("\n")
            if len(paths) > 3:
                paths = paths[2:-1]
                total_paths += paths
        return total_paths

    def __parse_path_list(self, path_list):
        '''
        neo4jのパス情報から以下情報を取得
        nodes: パスに含まれるnodeのリスト。srcからdstの順で含まれる
        relations: node間のリンクリンク情報。使用帯域など。srcからdstの順で含まれる
        min_bandwidth: 利用できる帯域
        hop_count: ホップ数
        exceeded_video_limitation_relations: ビデオの最低保証帯域を下回るリンク情報
        '''
        path_info_list = []
        for path in path_list:
            nodes = re.findall(r'\(([^)]*)\)', path)
            relations = re.findall(r'\[([^]]*)\]', path)
            hop_count, min_bandwidth, exceeded_video_limitation_relations = self.__create_summary_info(nodes, relations)
            if len(nodes) == len(set(nodes)):
                path_info_list.append({
                    "nodes": nodes,
                    "relations": relations,
                    "hop_count": hop_count,
                    "min_bandwidth": min_bandwidth,
                    "exceeded_video_limitation_relations": exceeded_video_limitation_relations
                })
        return path_info_list

    def __create_summary_info(self, nodes, relations):
        '''
        リンク情報からhop_count, min_bandwidth, exceeded_video_limitation_relationsを生成
        '''
        hop_count = len(nodes) - 1
        max_rate = 0
        exceeded_video_limitation_relations = []
        for i, relation in enumerate(relations):
            m = re.search(r'{(.*)}', relation)
            raw_props = m.group(1)
            prop_list = raw_props.split(",")
            for prop in prop_list:
                _key, _val = prop.split(":")
                _key, _val = _key.strip(), _val.strip()
                if _key == f"{nodes[i]}{nodes[i + 1]}":
                    if 100 - Decimal(_val) < LIMIT_VIDEO_BANDWIDTH:
                        exceeded_video_limitation_relations.append(i)
                    if max_rate < Decimal(_val):
                        max_rate = Decimal(_val)
        min_bandwidth = 100 - max_rate
        return hop_count, min_bandwidth, exceeded_video_limitation_relations

    def __update_video_flow_table(self, path_info_list):
        '''
        ビデオトラフィックのフロー情報更新
        '''
        sorted_path_info_list = sorted(path_info_list, key=lambda x: x['hop_count'])
        for info in sorted_path_info_list:
            # 最短パスの帯域が最低保証帯域を上回っている場合はそのままアップデート
            if info["min_bandwidth"] >= LIMIT_VIDEO_BANDWIDTH:
                self.__update(info["nodes"])
                return
             # 最短パスの帯域が最低保証帯域を下回っている場合は他トラフィックを切り替えてアップデート
            else:
                self.__modify_other_flow_table(info)
                self.__update(info["nodes"])
                return
        print("error in __update_video_flow_table")
        raise Exception

    def __update_other_flow_table(self, path_info_list, modify=False):
        '''
        他トラフィックのフロー情報更新
        '''
        sorted_path_info_list = sorted(path_info_list, key=lambda x: x['hop_count'])
        for info in sorted_path_info_list:
            nodes = info["nodes"]
            # 最短パスの帯域が最低保証帯域を上回っている場合はアップデート
            if info["min_bandwidth"] >= LIMIT_OTHER_BANDWIDTH:
                self.__update(info["nodes"])
                start_node = nodes[0]
                end_node = nodes[-1]
                # すでにトラフィックが終了している場合はそのままreturn
                if modify and not self.other_traffic[f"{start_node}{end_node}"]:
                    print("already completed the traffic")
                    return
                # 他トラフィック情報に登録
                self.other_traffic[f"{start_node}{end_node}"] = nodes
                return
        print("error found no path with enough bandwidth")
        raise Exception

    def __update(self, nodes):
        '''
        各Switchにフロー情報更新をリクエスト
        '''
        src_node_mac = HOST_LIST[int(nodes[0][1:]) - 1]["mac"]
        dst_node_mac = HOST_LIST[int(nodes[-1][1:]) - 1]["mac"]
        for i in range(len(nodes) - 1):
            port1, port2 = self.__get_port(nodes[i], nodes[i + 1])
            # 上り方向のフロー更新
            if nodes[i].startswith("s"):
                datapath = self.__get_datapath(nodes[i])
                ofproto = datapath.ofproto
                parser = datapath.ofproto_parser
                actions = [parser.OFPActionOutput(int(port1))]
                match = parser.OFPMatch(eth_src=src_node_mac, eth_dst=dst_node_mac)
                print(f"switch: {nodes[i]}, dpid: {datapath.id}, src: {src_node_mac}, dst: {dst_node_mac}, port: {port1}")
                self.add_flow(datapath, 1, match, actions)

            # 下り方向のフロー更新
            if nodes[i + 1].startswith("s"):
                datapath = self.__get_datapath(nodes[i + 1])
                ofproto = datapath.ofproto
                parser = datapath.ofproto_parser
                actions = [parser.OFPActionOutput(int(port2))]
                match = parser.OFPMatch(eth_src=dst_node_mac, eth_dst=src_node_mac)
                print(f"switch: {nodes[i + 1]}, dpid: {datapath.id}, src: {dst_node_mac}, dst: {src_node_mac}, port: {port2}")
                self.add_flow(datapath, 1, match, actions)

    def __get_port(self, node1, node2):
        '''
        node1とnode2の接続ポート情報を取得
        '''
        for li in LINK:
            if li[0] == node1 and li[2] == node2:
                port1 = li[1]
                port2 = li[3]
                break
            elif li[2] == node1 and li[0] == node2:
                connected_node = li[0]
                port1 = li[3]
                port2 = li[1]
                break
        return port1, port2

    def __get_datapath(self, switch_name):
        '''
        Switchに対応するdatapathを取得
        '''
        switch_id = int(switch_name[1:])
        dp_all = self.dpset.get_all()
        for dp in dp_all:
            if switch_id == dp[1].id:
                return dp[1]

    def __modify_other_flow_table(self, info):
        '''
        提案方式に従って、他トラフィックを選択し、フローテーブルを更新
        '''
        change_traffic_keys = set()
        for i in info["exceeded_video_limitation_relations"]:
            # ビデオ最低保証帯域を満たさないパスを含む他トラフィック情報を取得
            flg_find = 0
            node1 = info["nodes"][i]
            node2 = info["nodes"][i + 1]
            other_traffic_list = [{"key": k,  "nodes": v, "num_nodes": len(v)} for k, v in  self.other_traffic.items()]
            # 提案方式にしたがって、対象他トラフィックをソート
            if PATH_SELECT_ALGORITHM == PathSelectAlgorithm.SHORTEST_PATH:
                sorted_other_traffic_list = sorted(other_traffic_list, key=lambda x: x['num_nodes'])
            elif PATH_SELECT_ALGORITHM == PathSelectAlgorithm.LONGEST_PATH:
                sorted_other_traffic_list = sorted(other_traffic_list, key=lambda x: x['num_nodes'], reverse=True)
            elif PATH_SELECT_ALGORITHM == PathSelectAlgorithm.BANDWIDTH:
                other_traffic_list_add_rate = []
                for traffic in other_traffic_list:
                    tx_rate = self.other_traffic_rate.get(traffic["key"], {}).get("tx_rate", 0)
                    other_traffic_list_add_rate.append(traffic.update({"tx_rate": tx_rate}))
                sorted_other_traffic_list = sorted(other_traffic_list, key=lambda x: x['tx_rate'], reverse=True)
            elif PATH_SELECT_ALGORITHM == PathSelectAlgorithm.NO_CHANGE:
                raise Exception("not enough bandwidth")
            # 切り替える他トラフィックを決定
            for traffic in sorted_other_traffic_list:
                key = traffic["key"]
                other_traffic_nodes = traffic["nodes"]
                for j in range(len(other_traffic_nodes) - 1):
                    # 他トラフィックのパスにビデオ最低保証帯域を満たさないパスが含まれていれば、切り替える他トラフィックとする
                    if other_traffic_nodes[j] == node1 and other_traffic_nodes[j + 1] == node2:
                        change_traffic_keys.add(key)
                        flg_find = 1
                        break
                if flg_find == 1:
                    break
        # 決定した他トラフィックのフローテーブルを更新
        for key in change_traffic_keys:
            m = re.search(r'(h[0-9]*)(h[0-9]*)', key)
            src_node_name = m.group(1)
            dst_node_name = m.group(2)
            print(src_node_name)
            print(dst_node_name)
            print(self.other_traffic[key])
            path_list = self.__get_path_list("host", src_node_name, "host", dst_node_name, info["nodes"])
            path_info_list = self.__parse_path_list(path_list)
            self.__update_other_flow_table(path_info_list, True)
            

    def get_other_traffic(self):
        '''
        発生している他トラフィックのリストの取得（デバッグ用）
        '''
        return self.other_traffic

    def complete_other_traffic(self, src_host, dst_host):
        '''
        シミュレーションのスクリプトから他トラフィックの完了をリクエストされた時に実行されるメソッド
        '''
        # self.other_trafficから該当のトラフィックを削除
        del self.other_traffic[f"{src_host}{dst_host}"]


class RestController(ControllerBase):
    '''
    シミュレーションのフローテーブルをコントロールするためのrest apiの実装
    '''

    def __init__(self, req, link, data, **config):
        '''
        初期化
        '''
        super().__init__(req, link, data, **config)
        self.controller_app = data[controller_instance_name]

    @route('controller', other_traffic_url, methods=['POST'], requirements={})
    def update_other_traffic_flow_table(self, req, **kwargs):
        '''
        他トラフィックをアップデートするためのrest api
        '''

        controller_app = self.controller_app

        print(req)
        print(kwargs)

        try:
            body = req.json if req.body else {}
            src_host = body["src_host"]
            dst_host = body["dst_host"]
        except ValueError:
            raise Response(status=400)

        try:
            controller_app.update_flow_table(src_host, dst_host, "other")
            res = {"result": "success"}
        except Exception as e:
            print(e)
            res = {"result": "fail"}
        body = json.dumps(res)
        return Response(content_type='application/json', json_body=res)

    @route('controller', video_url, methods=['POST'], requirements={})
    def update_video_traffic_flow_table(self, req, **kwargs):
        '''
        ビデオトラフィックをアップデートするためのrest api
        '''

        controller_app = self.controller_app

        print(req)
        print(kwargs)

        try:
            body = req.json if req.body else {}
            src_host = body["src_host"]
            dst_host = body["dst_host"]
        except ValueError:
            raise Response(status=400)

        try:
            controller_app.update_flow_table(src_host, dst_host, "video")
            res = {"result": "success"}
        except Exception as e:
            print(e)
            res = {"result": "fail"}
        body = json.dumps(res)
        return Response(content_type='application/json', json_body=res)

    @route('controller', other_traffic_complete_url, methods=['POST'], requirements={})
    def complete_other_traffic(self, req, **kwargs):
        '''
        他トラフィックを完了するためのrest api
        '''

        controller_app = self.controller_app

        try:
            body = req.json if req.body else {}
            src_host = body["src_host"]
            dst_host = body["dst_host"]
        except ValueError:
            raise Response(status=400)

        try:
            controller_app.complete_other_traffic(src_host, dst_host)
            res = {"result": "success"}
        except Exception as e:
            print(e)
            res = {"result": "fail"}
        body = json.dumps(res)
        return Response(content_type='application/json', json_body=res)

    @route('controller', get_other_traffic, methods=['GET'], requirements={})
    def get_other_traffic(self, req, **kwargs):
        '''
        他トラフィックを情報を取得するためのrest api
        '''

        controller_app = self.controller_app

        try:
            res = controller_app.get_other_traffic()
        except Exception as e:
            print(e)
            res = {"result": "fail"}
        body = json.dumps(res)
        return Response(content_type='application/json', json_body=res)
