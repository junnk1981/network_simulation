import os
import json
from concurrent import futures
import time
from datetime import datetime
import copy

import requests

import random

from mininet.cli import CLI
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.term import makeTerm
from mininet.link import TCLink
from mininet.util import custom

from py2neo import Graph, Node, Relationship

from definitions.network import LINK
from definitions.host import HOST_LIST, NUM_HOST
from definitions.switch import SWITCH_LIST, NUM_SWITCH

# neo4jのdatabaseのパスワードを環境変数から取得
DB_PASS = os.getenv("DB_PASS", "password")
# フローコントローラーのポート番号
PORT = 6633

# フローコントローラーのREST APIのURI
OTHER_TRAFFIC_FLOW_UPDATE = 'http://127.0.0.1:8080/controller/other/flowtable'
VIDEO_TRAFFIC_FLOW_UPDATE = 'http://127.0.0.1:8080/controller/video/flowtable'
OTHER_TRAFFIC_FLOW_COMPLETE = 'http://127.0.0.1:8080/controller/other/complete'

# ログ設定
LOG_DIR = "results/" + datetime.now().strftime("%m%d%H%M%S")
os.makedirs(LOG_DIR)


class L2Network:
    def __init__(self):
        '''
        初期設定
        '''
        # mininetの初期化
        os.system('sudo mn -c')
        # mininetインスタンスの作成
        self.net = Mininet(controller=RemoteController)
        # mininetにコントローラーを塚
        self.c0 = self.net.addController('c0', port=PORT)
        self.list_switch = []
        self.list_host = []
        self.traffic = {}

        # neo4jのインスタンス化とDBのクリア
        self.graph = Graph(password=DB_PASS)
        self._delete_neo2j_graph()

    def _delete_neo2j_graph(self):
        '''
        neo4jのDBのデータを削除
        '''
        # SwitchとRelationを削除
        self.graph.run("MATCH (n:switch) OPTIONAL MATCH (n)-[r]-() DELETE r,n;")
        # NodeとRelationを削除
        self.graph.run("MATCH (n:host) OPTIONAL MATCH (n)-[r]-() DELETE r,n;")

    def create_network(self):
        '''
        mininetのネットワークを作成
        '''
        # neo4jのトランザクション開始
        tx = self.graph.begin()
        # Switchを作成
        for i in range(NUM_SWITCH):
            sw_name = SWITCH_LIST[i]["name"]
            # mininetにSwitchを登録
            sw = self.net.addSwitch(sw_name)
            # list_switchにSwitchを登録
            self.list_switch.append(sw)
            # neo4jにSwitchを登録
            tx.create(Node("switch", name=sw_name))

        # Hostを作成
        for i in range(NUM_HOST):
            host_name = HOST_LIST[i]["name"]
            # mininetにHostを登録
            host = self.net.addHost(host_name)
            # Hostでiperfサーバを起動
            host.cmd("iperf -s &")
            host.cmd("iperf -s -u&")
            # list_hostにHostを登録
            self.list_host.append(host)
            # neo4jにHostを登録
            tx.create(Node("host", name=host_name))
        # Commit
        tx.commit()

         # 100Mbpsのリンクを定義
        Band1mTCLink = custom(TCLink, bw=100)
        # neo4jのトランザクション開始
        # networkで定義している接続情報からリンクを作成
        tx = self.graph.begin()
        for link in LINK:
            # リンク情報からnodeを取得
            nodes = self._link_to_node(link)
            # mininet上のリンクを生成
            li = Band1mTCLink(nodes[0][0], nodes[1][0], port1=int(nodes[0][1]), port2=int(nodes[1][1]))

            # nodes[0]がSwitchの場合
            if nodes[0][0].name.startswith("s"):
                # nodes[0]に対応するneo4jインスタンスを取得
                node1 = self.graph.nodes.match("switch", name=nodes[0][0].name).first()
            # nodes[0]がHostの場合
            else:
                # nodes[0]に対応するneo4jインスタンスを取得
                node1 = self.graph.nodes.match("host", name=nodes[0][0].name).first()
                # このnodeの接続ポートにmacアドレスを割り当てる
                mac = list(filter(lambda x:x["name"] == nodes[0][0].name, HOST_LIST))[0]["mac"]
                li.intf2.setMAC(mac)
            # nodes[1]がSwitchの場合
            if nodes[1][0].name.startswith("s"):
                # node[1]に対応するneo4jインスタンスを取得
                node2 = self.graph.nodes.match("switch", name=nodes[1][0].name).first()
            # nodes[1]がHostの場合
            else:
                # node[1]に対応するneo4jインスタンスを取得
                node2 = self.graph.nodes.match("host", name=nodes[1][0].name).first()
                # このnodeの接続ポートにmacアドレスを割り当てる
                mac = list(filter(lambda x:x["name"] == nodes[1][0].name, HOST_LIST))[0]["mac"]
                li.intf2.setMAC(mac)

            # neo4j上のリンクを生成
            relation = dict(bandwidth=100)
            node1to2 = Relationship(node1, "connect", node2, **relation)
            tx.create(node1to2)

        # Commit
        tx.commit()

    def _link_to_node(self, link):
        '''
        リンク情報からそのリンクの両端のnode情報を取得
        '''
        nodes = []
        for node in [[link[0], link[1]], [link[2], link[3]]]:
            if node[0].startswith("s"):
                nodes.append([self.list_switch[int(node[0][1:]) - 1], node[1]])
            elif node[0].startswith("h"):
                nodes.append([self.list_host[int(node[0][1:]) - 1], node[1]])
            else:
                raise Exception
        return nodes


    def start_network(self):
        '''
        作成したネットワークの実行
        '''
        self.net.build()
        self.net.staticArp()
        self.c0.start()

        for switch in self.list_switch:
            switch.start([self.c0])

        self.net.startTerms()

        # self.c0.cmd("ryu-manager controller.py &")

        # cli = CLI(self.net)

    def stop_network(self):
        '''
        ネットワークの停止
        '''
        self.net.stop()

    def exec_simulation(self):
        '''
        シミュレーションの実行
        '''
        count = 0
        future_list = []
        with futures.ThreadPoolExecutor(max_workers=100) as executor:
            # ビデオサーバのインスタンスの定義
            video_server = [0, 10]
            # 他トラフィックを送信するインスタンスの定義
            client = [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18]
            
            ♯ 以下条件を満たすまで繰り返し
            while count < 100:
                print(f"count: {count}")
                flg_skip = False
                print(self.traffic)
                # この時点で発生しているトラフィックのリスト
                traffic_list = list(_key for _key, _val in self.traffic.items() if _val)
                # ビデオストリームの場合
                if random.randrange(2) == 0:
                    try:
                        _type = "video"
                        # 通信を行うノードの選択
                        node1 = video_server[random.randrange(2)]
                        node2 = client[random.randrange(17)]
                        # どちらが送信側になるかを選択
                        start_node, end_node = (node1, node2) if random.randrange(2) == 0 else (node2, node1)
                        for traffic in traffic_list:
                            # 送信ノードがすでに他のトラフィックで送信中であればスキップ
                            if traffic.startswith(f"h{start_node + 1}h"):
                                print("video skip")
                                print(traffic_list)
                                flg_skip = True
                        # すでにそのノード間で同様の通信が発生していない場合は通信を行う
                        if not self.traffic.get(f"h{start_node + 1}h{end_node + 1}") and flg_skip == False:
                            # 通信中のトラフィックとして登録
                            self.traffic[f"h{start_node + 1}h{end_node + 1}"] = True
                            # 別スレッドで通信を実行
                            future = executor.submit(self.__video_traffic, start_node=start_node, end_node=end_node)
                            future_list.append(future)
                            count += 1
                        # 上記以外の場合はスキップ
                        else:
                            print("video skip2")
                            pass
                            # print("hige")
                    except BaseException as e:
                        print(e)
                # 他トラフィックの場合
                else:
                    try:
                        _type = "other"
                        # 通信を行うノードの選択
                        client_tmp = copy.deepcopy(client)
                        tmp = random.randrange(17)
                        start_node = client_tmp[tmp]
                        del client_tmp[tmp]
                        end_node = client_tmp[random.randrange(16)]
                        for traffic in traffic_list:
                            # 送信ノードがすでに他のトラフィックで送信中であればスキップ
                            if traffic.startswith(f"h{start_node + 1}h"):
                                print("other skip")
                                print(traffic_list)
                                flg_skip = True
                        # すでにそのノード間で同様の通信が発生していない場合は通信を行う
                        if not self.traffic.get(f"h{start_node + 1}h{end_node + 1}") and flg_skip == False:
                            # 通信中のトラフィックとして登録
                            self.traffic[f"h{start_node + 1}h{end_node + 1}"] = True
                            # 別スレッドで通信を実行
                            future = executor.submit(self.__other_traffic, start_node=start_node, end_node=end_node)
                            future_list.append(future)
                            count += 1
                        else:
                            # 上記以外の場合はスキップ
                            print("other skip2")
                            pass
                            # print("huge")
                    except BaseException as e:
                        print(e)
                # 通信間隔を1秒開ける
                time.sleep(1)
            _ = futures.as_completed(fs=future_list)



    def __video_traffic(self, start_node, end_node):
        '''
        ビデオストリーム通信の実行
        '''
        print(f"start video. start_node: {start_node + 1}, end_node: {end_node + 1}")
        try:
            payload = {"src_host": f"h{start_node + 1}", "dst_host": f"h{end_node + 1}"}
            print(f"updating flow table for video. start_node: {start_node + 1}, end_node: {end_node + 1}")
            # フローをアップデート
            res = requests.post(VIDEO_TRAFFIC_FLOW_UPDATE, data=json.dumps(payload))
            # フローのアップデートを失敗した場合
            if res.json()["result"] == "fail":
                # ログの書き込み
                self.list_host[start_node].cmd(f"echo failed video stream >> {LOG_DIR}/result-video-h{start_node + 1}-h{end_node + 1}.txt")
                # 通信中のトラフィックから削除
                self.traffic[f"h{start_node + 1}h{end_node + 1}"] = False
                print(f"end video. start_node: {start_node + 1}, end_node: {end_node + 1}")
                return
            # 通信レートと通信時間を設定
            stream_rate = random.randrange(10, 30)
            stream_period = random.randrange(1, 20)
            print(f"sending traffic for video. start_node: {start_node + 1}, end_node: {end_node + 1}")
            # 通信の発生
            self.list_host[start_node].cmd(f"iperf -c 10.0.0.{end_node + 1} -u -b {stream_rate}M -t {stream_period}")
            print(f"update result file for video. start_node: {start_node + 1}, end_node: {end_node + 1}")
            # ログの書き込み
            self.list_host[start_node].cmd(f"echo success video stream >> {LOG_DIR}/result-video-h{start_node + 1}-h{end_node + 1}.txt")
        except BaseException as e:
            print(f"occur error video traffic. start_node: {start_node + 1}, end_node: {end_node + 1}, error: {e}")
        print(f"end video. start_node: {start_node + 1}, end_node: {end_node + 1}")
        # 通信中のトラフィックから削除
        self.traffic[f"h{start_node + 1}h{end_node + 1}"] = False

    def __other_traffic(self, start_node, end_node):
        '''
        他トラフィック通信の実行
        '''
        print(f"start other. start_node: {start_node + 1}, end_node: {end_node + 1}")
        try:
            payload = {"src_host": f"h{start_node + 1}", "dst_host": f"h{end_node + 1}"}
            print(f"updating flow table for other. start_node: {start_node + 1}, end_node: {end_node + 1}")
            # フローをアップデート
            res = requests.post(OTHER_TRAFFIC_FLOW_UPDATE, data=json.dumps(payload))
            # フローのアップデートを失敗した場合
            if res.json()["result"] == "fail":
                # ログの書き込み
                self.list_host[start_node].cmd(f"echo failed other stream >> {LOG_DIR}/result-other-h{start_node + 1}-h{end_node + 1}.txt")
                # 通信中のトラフィックから削除
                self.traffic[f"h{start_node + 1}h{end_node + 1}"] = False
                print(f"end other. start_node: {start_node + 1}, end_node: {end_node + 1}")
                return
            # 通信データ量の設定
            data_size = random.randrange(100, 900)
            print(f"sending traffic for other. start_node: {start_node + 1}, end_node: {end_node + 1}")
            # 通信の発生
            self.list_host[start_node].cmd(f"iperf -c 10.0.0.{end_node + 1} -n {data_size}M | grep sec >> {LOG_DIR}/result-other-h{start_node + 1}-h{end_node + 1}.txt")
            print(f"complete traffic for othe. start_node: {start_node + 1}, end_node: {end_node + 1}")
            # 他トラフィックの完了処理
            res = requests.post(OTHER_TRAFFIC_FLOW_COMPLETE, data=json.dumps(payload))
        except BaseException as e:
            print(f"occur error other traffic. start_node: {start_node + 1}, end_node: {end_node + 1}, error: {e}")
        print(f"end other. start_node: {start_node + 1}, end_node: {end_node + 1}")
        # 通信中のトラフィックから削除
        self.traffic[f"h{start_node + 1}h{end_node + 1}"] = False


if '__main__' == __name__:

    # ネットワーク初期化
    l2net = L2Network()
    # ネットワークの作成
    l2net.create_network()
    # ネットワークの開始
    l2net.start_network()
    # コントローラを手動開始するためにインタラクションを挿入
    input()
    # シミュレーションの開始
    l2net.exec_simulation()
    # ネットワークの終了
    l2net.stop_network()



