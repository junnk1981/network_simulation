import os
import json
from concurrent import futures
import time

import requests

import random

from mininet.cli import CLI
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.term import makeTerm
from mininet.link import TCLink
from mininet.util import custom

from py2neo import Graph, Node, Relationship

from definitions.network import LINK, SWITCH_NAME, HOST_NAME
from definitions.host import HOST_LIST, NUM_HOST
from definitions.switch import SWITCH_LIST, NUM_SWITCH

DB_PASS = os.getenv("DB_PASS", "password")
PORT = 6633

OTHER_TRAFFIC_FLOW_UPDATE = 'http://127.0.0.1:8080/controller/other/flowtable'
VIDEO_TRAFFIC_FLOW_UPDATE = 'http://127.0.0.1:8080/controller/video/flowtable'
OTHER_TRAFFIC_FLOW_COMPLETE = 'http://127.0.0.1:8080/controller/other/complete'

class L2Network:
    def __init__(self):
        # clear mininet
        os.system('sudo mn -c')
        self.net = Mininet(controller=RemoteController)
        self.c0 = self.net.addController('c0', port=PORT)
        self.list_switch = []
        self.list_host = []

        print("#### test!!!")

        # initialize neo4j graph
        self.graph = Graph(password=DB_PASS)
        self._delete_neo2j_graph()
        # self.graph.schema.create_uniqueness_constraint("switch", "name")
        # self.graph.schema.create_uniqueness_constraint("host", "name")

    def _delete_neo2j_graph(self):
        # self.graph.cypher.execute("MATCH (n) OPTIONAL DETACH DELETE n")
        print("#### deleting neo4j")
        # schema = self.graph.run("call db.schemaStatements()")
        # constraint = str(schema).split("\n")
        # print(constraint[0])
        # print(constraint[1])
        self.graph.run("MATCH (n:switch) OPTIONAL MATCH (n)-[r]-() DELETE r,n;")
        self.graph.run("MATCH (n:host) OPTIONAL MATCH (n)-[r]-() DELETE r,n;")
        # self.graph.run("DROP CONSTRAINT constraint_name [IF EXISTS];")

    def create_network(self):
        # create switch
        tx = self.graph.begin()
        for i in range(NUM_SWITCH):
            sw_name = SWITCH_NAME.format(
                num=str(i + 1)
            )
            sw = self.net.addSwitch(sw_name)
            self.list_switch.append(sw)
            tx.create(Node("switch", name=sw_name))

        # create host
        for i in range(NUM_HOST):
            host_name = HOST_NAME.format(
                num=str(i + 1)
            )
            host = self.net.addHost(host_name)
            host.cmd("iperf -s &")
            self.list_host.append(host)
            tx.create(Node("host", name=host_name))
        tx.commit()

        # create link
        Band1mTCLink = custom(TCLink, bw=100)
        count = 0
        tx = self.graph.begin()
        for link in LINK:
            nodes = self._link_to_node(link)
            li = Band1mTCLink(nodes[0][0], nodes[1][0], port1=int(nodes[0][1]), port2=int(nodes[1][1]))
            if nodes[0][0].name.startswith("s"):
                node1 = self.graph.nodes.match("switch", name=nodes[0][0].name).first()
            else:
                node1 = self.graph.nodes.match("host", name=nodes[0][0].name).first()
                mac = list(filter(lambda x:x["name"] == nodes[0][0].name, HOST_LIST))[0]["mac"]
                li.intf2.setMAC(mac)
            if nodes[1][0].name.startswith("s"):
                node2 = self.graph.nodes.match("switch", name=nodes[1][0].name).first()
            else:
                node2 = self.graph.nodes.match("host", name=nodes[1][0].name).first()
                mac = list(filter(lambda x:x["name"] == nodes[1][0].name, HOST_LIST))[0]["mac"]
                li.intf2.setMAC(mac)

            relation = dict(band_usage=100, rate=0)
            node1to2 = Relationship(node1, "connect", node2, **relation)
            # node2to1 = Relationship(node2, "connect", node1, **relation)
            tx.create(node1to2)
            # tx.create(node2to1)
            # if count < 3:
            #     li.intf1.setMAC(f"0:1:0:0:0:{count}")
            #     li.intf2.setMAC(f"0:0:0:0:1:{count}")
            # if count < 10:
            #     li.intf1.setMAC(f"0:0:0:0:0:{count}")
            #     li.intf2.setMAC(f"0:0:0:0:1:{count}")
            # elif count < 100:
            #     li.intf1.setMAC(f"0:0:0:{count // 10}:0:{count % 10}")
            #     li.intf2.setMAC(f"0:0:0:{count // 10}:1:{count % 10}")

            count += 1
        tx.commit()

    def _link_to_node(self, link):
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
        # h1.cmd("python -m SimpleHTTPServer 80&")
        # h2.cmd("python -m SimpleHTTPServer 81&")
        self.net.build()
        self.net.staticArp()
        self.c0.start()

        for switch in self.list_switch:
            switch.start([self.c0])

        self.net.startTerms()

        self.c0.cmd("ryu-manager controller.py &")

        # cli = CLI(self.net)

    def stop_network(self):
        self.net.stop()

    def exec_simulation(self):
        other_count = 0
        other_fail_count = 0
        video_count = 0
        video_fail_count = 0
        future_list = []
        with futures.ThreadPoolExecutor(max_workers=4) as executor:
            # while True:
            for i in range(4):
                _type = "other"
                start_node = random.randrange(NUM_HOST)
                end_node = random.randrange(NUM_HOST)
                if start_node == end_node:
                    continue
                if random.randrange(2) == 0:
                    _type = "video"

                if _type == "other":
                    future = executor.submit(self.__other_traffic, start_node=start_node, end_node=end_node)
                    future_list.append(future)
                else:
                    future = executor.submit(self.__video_traffic)
                _ = futures.as_completed(fs=future_list)



    def __video_traffic(self):
        print("start video")

    def __other_traffic(self, start_node, end_node):
        print("start other")
        # other_count += 1
        payload = {"src_host": f"h{start_node + 1}", "dst_host": f"h{end_node + 1}"}
        res = requests.post(OTHER_TRAFFIC_FLOW_UPDATE, data=json.dumps(payload))
        if res.json()["result"] == "fail":
            print("fail")
            other_fail_count += 1
            return
        data_size = random.randrange(10, 90)
        self.list_host[start_node].cmd(f"iperf -c 10.0.0.{end_node + 1} -n {data_size}M >> result-h{start_node + 1}-h{end_node + 1}.txt")
        res = requests.post(OTHER_TRAFFIC_FLOW_COMPLETE, data=json.dumps(payload))
        print("end")


if '__main__' == __name__:

    l2net = L2Network()
    l2net.create_network()
    l2net.start_network()
    time.sleep(10)
    l2net.exec_simulation()
    l2net.stop_network()



