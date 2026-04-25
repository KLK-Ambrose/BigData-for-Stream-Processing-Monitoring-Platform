# 🌊 工业水泵智能流处理监控平台 

## 📑 项目简介
本项目旨在构建一个端到端的工业物联网 (IIoT) 设备监控体系。基于 Docker 搭建的 3 节点分布式大数据集群，完美落地了企业级 **Lambda 混合架构**。
系统打通了从底层物理信号到顶层交互式大屏的完整链路，兼顾了海量数据的**离线高吞吐批处理**与**毫秒级低延迟流处理**。

**核心技术链路：**
`HDFS 数据湖` → `Spark 分布式清洗与机器学习` → `Hive 离线数仓 + HBase 实时宽表` → `Windows 多线程交互大屏`

---

## 🚀 极速启动指南

### 1. 宿主机环境配置 (CentOS)
开机后，首先在虚拟机宿主机执行以下网络与容器拉起操作：

```bash
# 1. 关闭防火墙，避免拦截外部访问请求
systemctl stop firewalld

# 2. 启动 Docker 集群节点容器
docker start master worker1 worker2

# 3. 建立端口物理转发 (极度重要：打通容器内外的网络隔离)
socat TCP-LISTEN:9090,fork TCP:172.20.0.5:9090 &
socat TCP-LISTEN:10000,fork TCP:172.20.0.5:10000 &

# 4. 进入主节点容器
docker exec -it master /bin/bash
```

### 2. 唤醒大数据生态核心 (Master 容器内)
进入 `master` 容器后，按依赖顺序逐层点亮大数据组件：

```bash
# 1. 启动底层基石：Hadoop (HDFS + YARN)
/usr/local/hadoop/sbin/start-all.sh

# 2. 启动实时宽表：HBase (含内置 ZooKeeper)
/usr/local/hbase/bin/start-hbase.sh

# 3. 开启跨语言通信桥梁：HBase Thrift 服务 (监听端口 9090)
/usr/local/hbase/bin/hbase-daemon.sh start thrift

# 4. 启动离线数仓：Hive Metastore 与 HiveServer2 (监听端口 10000)
# (采用分离部署模式，防止高并发下发生 OOM)
nohup hive --service metastore > /root/hive-meta.log 2>&1 &
nohup hive --service hiveserver2 > /root/hive-server.log 2>&1 &
```

### 3. 启动前端可视化大屏 (Windows 本机)
在确保宿主机转发正常且组件启动后，于 Windows 端执行：
```bash
python Lambda_Dashboard.py
```
> **💡 界面说明：** 大屏上半部分展示由 Hive 支撑的宏观 KPI 统计，下半部分动态渲染由 HBase 极速驱动的传感器心电图波形。

---

## 🩺 系统健康检查
在 `master` 容器内执行 `jps` 命令，健康的满血集群预期将包含以下进程：
* **Hadoop:** `NameNode`, `SecondaryNameNode`, `ResourceManager`
* **HBase:** `HMaster`, `HRegionServer` (如兼任), `HQuorumPeer`
* **Spark:** `Master`
* **Hive:** `RunJar` (通常为两个，对应 Metastore 和 HiveServer2)

进入 Worker 容器执行 `jps`，预期包含：
* `DataNode`, `NodeManager`, `HRegionServer`, `Worker`

---

## 🛑 安全关机操作
为防止 HDFS 产生坏块或 HBase 发生数据损坏，请**务必**在 `master` 容器内按如下相反顺序安全终止服务：

```bash
# 1. 关闭计算引擎
/usr/local/spark/sbin/stop-all.sh

# 2. 安全关闭 HBase (若直接 stop 卡死，可先停用 daemon)
cd /usr/local/hbase/bin
hbase-daemons.sh stop master
hbase-daemons.sh stop regionserver
stop-hbase.sh

# 3. 关闭存储底座
/usr/local/hadoop/sbin/stop-all.sh
```
确认服务安全关闭后，输入 `exit` 退出容器，并在宿主机执行 `poweroff`。