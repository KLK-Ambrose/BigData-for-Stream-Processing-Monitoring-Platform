-- Hive 数仓建模与 HBase 映射脚本
-- 运行环境：master 容器内的 Beeline 客户端 (beeline -u jdbc:hive2://localhost:10000 -n root)
-- 核心功能：创建数据库，映射 HDFS 的离线统计数据，并打通 HBase 的外部映射宽表

-- 1. 创建并使用项目专属数据库
CREATE DATABASE IF NOT EXISTS sensor_db;
USE sensor_db;

-- 2. 建立外部表，直接映射 Spark 输出的预测结果 Parquet 目录 (用于离线宏观统计)
CREATE EXTERNAL TABLE IF NOT EXISTS sensor_predictions (
    `timestamp` TIMESTAMP,
    `machine_status` STRING,
    `label` INT,
    `prediction` DOUBLE
)
STORED AS PARQUET
LOCATION 'hdfs://master:9000/user/root/sensor_project/output/predictions';

-- 3. 建立 HBase 实时映射表 (用于连通实时流层)
-- 注意：执行此语句前，必须先在 HBase shell 中执行 create 'sensor_wave', 'status', 'wave'
CREATE EXTERNAL TABLE IF NOT EXISTS hive_hbase_sensor(
    row_key string,
    s04 float,
    s10 float,
    pred float
)
STORED BY 'org.apache.hadoop.hive.hbase.HBaseStorageHandler'
WITH SERDEPROPERTIES ("hbase.columns.mapping" = ":key,wave:s04,wave:s10,status:pred")
TBLPROPERTIES ("hbase.table.name" = "sensor_wave");