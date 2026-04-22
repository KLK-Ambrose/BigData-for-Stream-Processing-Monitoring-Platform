# 运行环境：master 容器（Spark 数据清洗脚本）
# 执行命令：/usr/local/spark/bin/spark-submit /root/data_cleaning.py
# 核心功能：读取原始 CSV，剔除全空列 sensor_15，填充缺失值，格式化时间戳，并转换为 Parquet 格式输出至 HDFS
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, to_timestamp

print("👉 [1/5] 正在初始化 Spark 集群...")
spark = SparkSession.builder \
    .appName("PumpSensorDataCleaning") \
    .getOrCreate()

print("👉 [2/5] 正在从 HDFS 读取原始数据...")
raw_df = spark.read.csv("hdfs://master:9000/user/root/sensor_project/input/sensor.csv", 
                        header=True, 
                        inferSchema=True)

# 打印原始数据量
total_rows = raw_df.count()
print(f"✅ 原始数据加载成功，共计 {total_rows} 条记录。")

print("👉 [3/5] 开始清洗数据 (处理缺失值与无用列)...")

# 剔除无意义的序号列和 100% 缺失的废弃节点 sensor_15
clean_df = raw_df.drop("Unnamed: 0", "sensor_15")

# 转换时间戳格式 (将字符串转换为 Spark 原生的 Timestamp 类型)
clean_df = clean_df.withColumn("timestamp", to_timestamp(col("timestamp"), "yyyy-MM-dd HH:mm:ss"))

# 处理其他传感器的偶然缺失值 (NaN)，这里将少量空值填充为 0
clean_df = clean_df.fillna(0)

# 数据探勘展示
print("👉 [4/5] 数据清洗完成！数据结构(Schema)如下：")
clean_df.printSchema()

print("👉 标签状态分布统计：")
clean_df.groupBy("machine_status").count().show()

print("👉 [5/5] 将清洗后的数据以 Parquet 格式写入 HDFS 数据仓库...")
output_path = "hdfs://master:9000/user/root/sensor_project/output/cleaned_data"
clean_df.write.mode("overwrite").parquet(output_path)

print(f"🎉 恭喜！数据清洗流程全部跑通，数据已保存至：{output_path}")

# 关闭 Spark 任务
spark.stop()