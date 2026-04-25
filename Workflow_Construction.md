# 🛠️ 工业水泵系统 - 架构构建与工程全流程

本文档详细记录了系统从数据接入到前端大屏展现的 6 个核心阶段。

## 阶段一：数据摄入与入湖 (Data Ingestion)
* **目标：** 将原始 CSV 数据无损存入 HDFS 数据湖 ODS 层。
* **执行步骤：**
  1. 将原始 `sensor.csv`（约 120MB，22万条高频采样数据）上传至 CentOS 宿主机 `/root/`。
  2. 将数据跨越隔离层拷贝至主容器，并推入 HDFS：
     ```bash
     docker cp /root/sensor.csv master:/
     docker exec -it master /bin/bash
     
     hdfs dfs -mkdir -p /user/root/sensor_project/input
     hdfs dfs -mkdir -p /user/root/sensor_project/output
     hdfs dfs -put /sensor.csv /user/root/sensor_project/input/
     ```

## 阶段二：分布式清洗与预处理 (Spark ETL)
* **目标：** 应对真实工业数据脏乱差问题，转换存储格式提升 I/O 效率。
* **执行步骤：** 编写并提交 `data_cleaning.py` 脚本，核心操作包含：
  * 剔除无意义序号列 `Unnamed: 0` 及 100% 缺失废弃节点 `sensor_15`。
  * 将字符串时间转换为原生 `Timestamp` 类型。
  * 缺失值填充 (0 值处理)。
  * **工程突破：** 将清洗后的数据转存为高压缩率的 **Parquet 列式存储格式**。
  ```bash
  /usr/local/spark/bin/spark-submit /root/data_cleaning.py
  ```

## 阶段三 & 四：特征工程与智能建模 (Spark MLlib)
* **目标：** 解决极端样本不平衡痛点，训练预测模型提取数据价值。
* **执行步骤：**
  编写并提交 `model_training.py` 脚本：
  1. **标签重构：** 聚合 `BROKEN` 与 `RECOVERING` 状态为异常标签 `1`，实现二分类转换。
  2. **特征工程：** 运用 `VectorAssembler` 与 `StandardScaler` 实现多维向量化与量纲标准化。
  3. **模型训练：** 构建随机森林分类器 (`numTrees=20`, `maxDepth=5`)。
  ```bash
  /usr/local/spark/bin/spark-submit /root/model_training.py
  ```
  > 🏆 模型在测试集上取得 **AUC 0.9998** 的优异表现，预测结果落盘至 HDFS。

## 阶段五：数仓建模与 Lambda 双路分流 (Storage)

### 1. 宏观层：Hive 离线数仓
* **目标：** 支撑复杂的全局维度健康度 KPI 聚合查询。
* **操作：** 在 Beeline 中建立外部表映射预测结果，零拷贝实现数据访问。
  ```sql
  CREATE DATABASE IF NOT EXISTS sensor_db;
  USE sensor_db;
  CREATE EXTERNAL TABLE sensor_predictions (
      timestamp TIMESTAMP, machine_status STRING, label INT, prediction DOUBLE
  ) STORED AS PARQUET
  LOCATION 'hdfs://master:9000/user/root/sensor_project/output/predictions';
  ```

### 2. 微观层：HBase 实时宽表
* **目标：** 承载高频时序切片，提供毫秒级波形检索。
* **操作：** 1. 开启 Thrift RPC 服务：`/usr/local/hbase/bin/hbase-daemon.sh start thrift`。
  2. 于 HBase Shell 中构建包含 `status` 与 `wave` 列族的宽表 `sensor_wave`。
  3. 修改并运行 Python 批量入库脚本 `push_to_hbase.py`。

## 阶段六：多线程交互大屏 (Visualization)
* **目标：** 打造现代工业风的监控看板，动态展现数据流。
* **执行步骤：**
  1. 安装本地依赖：`pip install customtkinter matplotlib happybase pyhive pandas`
  2. **双擎并发调度：** 编写 `Lambda_Dashboard.py`
     * **线程 A (慢速)：** 每 30s 轮询 Hive 更新月度/全局统计。
     * **线程 B (极速)：** 以 10Hz 频次通过 Thrift 拉取 HBase 绘制动态波形。
  3. **防断流模拟：** 额外配置 `mock_sensor_stream.py` 以固定频率向 HBase 推入带有随机突变异常的新数据，保持大屏永久运转。