import os

from py2neo import Graph, Node, Relationship

# neo4jのdatabaseのパスワードを環境変数から取得
DB_PASS = os.getenv("DB_PASS", "password")

class RouteFacade:

    graph = Graph(password=DB_PASS)

    @classmethod
    def get_shortest_path(cls, src_type, src_node_name, dst_type, dst_node_name):
        '''
        neo4jからsrcとdst間の最短パスを取得する
        '''
        string = f'MATCH p = shortestPath((s:{src_type} {{name:"{src_node_name}"}})-[:connect*0..]-(d:{dst_type} {{name:"{dst_node_name}"}})) RETURN p'
        res = cls.__query_path(string)
        return res[0]

    @classmethod
    def get_connected_host(cls, switch_name):
        '''
        neo4jからスイッチに接続されているhostを取得する
        '''
        string = f'MATCH (s:switch {{name:"{switch_name}"}})-[:connect]->(d:host) RETURN d'
        res = cls.graph.run(string)
        lines = str(res).split("\n")
        hosts = []
        for i in range(len(lines)):
            if i < 2:
                continue
            m = re.search(r'^ \([^ ]* {name: \'(.*)\'}\)', lines[i])
            logger.debug(lines[i])
            if m:
                hosts.append(m.group(1))
        
        return hosts

    @classmethod
    def __query_path(cls, query_string):
        res = cls.graph.run(query_string)
        lines = str(res).split("\n")
        return lines[2:-1]

    @classmethod
    def update_bandwitdh_usage(cls, switch_name, connected_node, port, tx_rate, rx_rate):
        '''
        ポート統計情報を元にneo4jの情報をアップデート
        '''
        tx_rate_mb = tx_rate / 1024 / 1024
        rx_rate_mb = rx_rate / 1024 / 1024

        # neo4jで管理している各リンクの使用帯域情報をアップデート
        if connected_node.startswith('s'):
            string = f'MATCH (s:switch {{name:"{switch_name}"}})-[c:connect]->(d:switch{{name:"{connected_node}"}}) SET c.{switch_name}{connected_node} = {tx_rate_mb}, c.{connected_node}{switch_name} = {rx_rate_mb} RETURN d'
        elif connected_node.startswith('h'):
            string = f'MATCH (s:switch {{name:"{switch_name}"}})-[c:connect]->(d:host{{name:"{connected_node}"}}) SET c.{switch_name}{connected_node} = {tx_rate_mb}, c.{connected_node}{switch_name} = {rx_rate_mb} RETURN d'
        else:
            raise Exception('Internal Error')
        cls.graph.run(string)

    @classmethod
    def get_path_list(cls, src_type, src_node_name, dst_type, dst_node_name, filter_path = None):
        '''
        src_node_nameからdst_node_nameへのパス情報を取得する
        filter_pathに含まれるパスは含まない
        '''
        where_string = "WHERE ALL(s IN NODES(p) WHERE SINGLE(t IN NODES(p) WHERE s = t)) "
        # filter_pathが含まれる場合はfilter条件を追加
        if filter_path:
            where_string += "AND ALL(n IN RELATIONSHIPS(p) WHERE not "
            for i in range(len(filter_path) - 1):
                where_string += f'(startNode(n).name = "{filter_path[i]}" and endNode(n).name = "{filter_path[i + 1]}") and not '
                where_string += f'(startNode(n).name = "{filter_path[i + 1]}" and endNode(n).name = "{filter_path[i]}") and not '
            where_string = where_string[:-9] + ") "
        string = f'MATCH p = (h:{src_type} {{name:"{src_node_name}"}})-[:connect*0..]-(d:{dst_type} {{name:"{dst_node_name}"}}) {where_string} RETURN p;'
        return cls.__query_path(string)



