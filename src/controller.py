import os
import re
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib import hub
from ryu.controller import dpset

from operator import attrgetter

from py2neo import Graph, Node, Relationship

from definitions.host import HOST_LIST
from definitions.network import LINK

DB_PASS = os.getenv("DB_PASS", "password")


class ExampleSwitch13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
        'dpset': dpset.DPSet,
    }

    def __init__(self, *args, **kwargs):
        super(ExampleSwitch13, self).__init__(*args, **kwargs)
        # initialize mac address table.
        self.mac_to_port = {}
        self.datapaths = {}
        self.stats_info = {}
        self.dpset = kwargs['dpset']
        self.graph = Graph(password=DB_PASS)
        self.monitor_thread = hub.spawn(self._monitor)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.stats_info[str(datapath.id)] = {}
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        self.__initial_setup_flow_table(datapath)

    def __get_shortest_path(self, src_type, src_node_name, dst_type, dst_node_name):
        string = f'MATCH p = shortestPath((s:{src_type} {{name:"{src_node_name}"}})-[:connect*0..]-(d:{dst_type} {{name:"{dst_node_name}"}})) RETURN p'
        return self.graph.run(string)

    def __get_connected_host(self, datapath_id):
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
        switch_name = f"s{datapath.id}"
        parser = datapath.ofproto_parser
        for host in HOST_LIST:
            res = self.__get_shortest_path("switch", switch_name, "host", host["name"])
            lines = str(res).split("\n")
            m = re.search(r'^ \((s[\w]*)\)[^(]*\(([sh][\w]*)\).*', lines[2])
            next_node_name = m.group(2)
            out_port = self.__get_ports(next_node_name, switch_name)
            actions = [parser.OFPActionOutput(int(out_port))]
            for src_host in HOST_LIST:
                if src_host == host:
                    continue
                match = parser.OFPMatch(eth_src=src_host["mac"], eth_dst=host["mac"])
                self.add_flow(datapath, 1, match, actions)
                
    def __get_ports(self, dst_node, switch):
        for li in LINK:
            if li[0] == dst_node and li[2] == switch:
                out_port = li[3]
            elif li[2] == dst_node and li[0] == switch:
                out_port = li[1]
        return out_port




    def add_flow(self, datapath, priority, match, actions):
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
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(10)

    def _request_stats(self, datapath):
        self.logger.debug('send stats request: %016x', datapath.id)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id

        for stat in sorted(body, key=attrgetter('port_no')):
            port_no, rx_rate, tx_rate = self.__update_stats_info(dpid, stat)
            self.__update_bandwitdh_usage(switch_name=f's{dpid}', port=str(port_no), rx_rate=rx_rate, tx_rate=tx_rate)

    def __update_stats_info(self, dpid, stat):
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
        tx_rate_mb = tx_rate / 1024 / 1024
        rx_rate_mb = rx_rate / 1024 / 1024
        connected_node = None
        for li in LINK:
            if li[0] == switch_name and li[1] == port:
                connected_node = li[2]
            elif li[2] == switch_name and li[3] == port:
                connected_node = li[0]

        if not connected_node:
            return

        if connected_node.startswith('s'):
            string = f'MATCH (s:switch {{name:"{switch_name}"}})-[c:connect]->(d:switch{{name:"{connected_node}"}}) SET c.{switch_name}{connected_node} = {tx_rate_mb}, c.{connected_node}{switch_name} = {rx_rate_mb} RETURN d'
        elif connected_node.startswith('h'):
            string = f'MATCH (s:switch {{name:"{switch_name}"}})-[c:connect]->(d:host{{name:"{connected_node}"}}) SET c.{switch_name}{connected_node} = {tx_rate_mb}, c.{connected_node}{switch_name} = {rx_rate_mb} RETURN d'
        else:
            raise Exception('Internal Error')
        self.graph.run(string)
        

