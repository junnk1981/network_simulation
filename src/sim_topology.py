import os

from mininet.cli import CLI
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.term import makeTerm
from mininet.link import TCLink
from mininet.util import custom

from py2neo import Graph, Node, Relationship

from definitions.network import NUM_SWITCH, NUM_HOST, LINK, SWITCH_NAME, HOST_NAME

DB_PASS = os.getenv("DB_PASS", "password")
PORT = 6633

class L2Network:
    def __init__(self):
        # clear mininet
        os.system('sudo mn -c')
        self.net = Mininet(controller=RemoteController)
        self.c0 = self.net.addController('c0', port=PORT)
        self.list_switch = []
        self.list_host = []

        # # initialize neo4j graph
        # print(DB_PASS)
        # self.graph = Graph(password=DB_PASS)
        # self._delete_neo2j_graph()
        # self.graph.schema.create_uniqueness_constraint("switch", "name")
        # self.graph.schema.create_uniqueness_constraint("host", "name")

    def _delete_neo2j_graph(self):
        # self.graph.cypher.execute("MATCH (n:switch) OPTIONAL MATCH (n)-[r]-() DELETE r,n")
        # self.graph.cypher.execute("MATCH (n:host) OPTIONAL MATCH (n)-[r]-() DELETE r,n")
        # for switch in self.graph.find("switch"):
        #     self.graph.delete(switch)
        # for host in self.graph.find("host"):
        #     self.graph.delete(host)
        pass

    def create_network(self):
        # create switch
        for i in range(NUM_SWITCH):
            self.list_switch.append(
                self.net.addSwitch(
                    SWITCH_NAME.format(
                        num=str(i)
                    )
                )
            )

        # create host
        for i in range(NUM_HOST):
            self.list_host.append(
                self.net.addHost(
                    HOST_NAME.format(
                        num=str(i)
                    )
                )
            )

        # create link
        Band1mTCLink = custom(TCLink, bw=100)

        for link in LINK:
            nodes = self._link_to_node(link)
            Band1mTCLink(nodes[0], nodes[1])

    def _link_to_node(self, link):
        nodes = []
        for node in link:
            if node.startswith("s"):
                nodes.append(self.list_switch[int(node[1:]) - 1])
            elif node.startswith("h"):
                nodes.append(self.list_host[int(node[1:]) - 1])
            else:
                raise Exception
        return nodes


    def start_network(self):
        # h1.cmd("python -m SimpleHTTPServer 80&")
        # h2.cmd("python -m SimpleHTTPServer 81&")
        self.net.build()
        self.c0.start()

        for switch in self.list_switch:
            switch.start([self.c0])

        self.net.startTerms()

        cli = CLI(self.net)

    def stop_network(self):
        self.net.stop()

if '__main__' == __name__:

    l2net = L2Network()
    l2net.create_network()
    l2net.start_network()
    l2net.stop_network()



