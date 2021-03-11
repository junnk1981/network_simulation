# network_simulation

## 前提条件

* 以下をインストール
  * virtual box
  * vagrant

## 使い方 

### 仮想環境の起動

```
vagrant up
```

### 初期セットアップ

* neo4jのDBのセットアップ
  * http://127.0.0.1:7474 にブラウザでアクセス
  * id: neo4j / pass: neo4j でログインし、パスワードを設定

### シミュレーションの起動

* vagrant up で virtual boxが起動し、UbuntuのUIが表示されているので id: vagrant / pass: vagrant でログインする
* Terminalを起動し、以下のコマンドを実行する

```
sudo su
cd /vagrant_data/src
export DB_PASS=<初期セットアップで設定したDBのパスワード>
例：export DB_PASS=12345
python3 sim_topology.py
```

* terminalが複数立ち上がるので、[c0: controller]のterminalを探し、以下を実行する

```
ryu-manager controller.py
```

* sim_topology.pyを実行したterminalに戻り、Enterキーを押すとシミュレーションが実行され、src/results配下に結果が出力される

### シミュレーションの結果

* result-other-ホスト1-ホスト2.txtファイル
  * ホスト1からホスト2への他トラフィック通信の結果
  * 成功の場合は、転送時間・転送量・転送速度が書き込まれる
  * 失敗時はfailと書き込まれる
* result-video-ホスト1-ホスト2.txtファイル
  * ホスト1からホスト2へのビデオトラフィック通信の結果
  * 成功の場合はsuccessと書き込まれる
  * 失敗時はfailと書き込まれる

### チューニング

* ビデオストリームのレートの調整
  * sim_topology.pyの以下の行を書き換える。以下は10Mbps - 30Mbpsの間の通信速度をランダムにとる場合
  * stream_rate = random.randrange(10, 30)
* ビデオストリームの時間の調整
  * sim_topology.pyの以下の行を書き換える。以下は10秒 - 30秒の間をランダムにとる場合
  * stream_period = random.randrange(10, 30)
* 他トラフィックのデータサイズの調整
  * sim_topology.pyの以下の行を書き換える。以下は100MB - 900MBの間をランダムにとる場合
  * data_size = random.randrange(100, 900)
* トラフィックの発生間隔の調整
  * sim_topology.pyの以下の行を書き換える。以下は間隔が5秒の場合
  * time.sleep(5)
* トラフィック発生量の調整
  * sim_topology.pyの以下の行を書き換える。以下は最大100回通信を発生させる場合
  * while count < 100:
* 切り替えアルゴリズムの変更
  * controller.pyの以下の行を書き換える
  * PATH_SELECT_ALGORITHM = PathSelectAlgorithm.LONGEST_PATH
     * 切り替えなし：PathSelectAlgorithm.NO_CHANGE
     * ホップ数小を優先：PathSelectAlgorithm.SHORTEST_PATH
     * ホップ数大を優先：PathSelectAlgorithm.LONGEST_PATH


