# 运行环境：master 容器（HBase 实时流模拟入库脚本）
# 执行命令：/usr/local/python3/bin/python3 /root/push_to_hbase.py
# 核心功能：绕过底层 GLIBC 版本冲突，读取本地硬盘中的 Parquet 文件，提取关键波形特征，并通过 HappyBase 以 Batch 形式极速推入 HBase。
import happybase
import pandas as pd

print("🚀 [1/3] 正在从本地读取预测结果与清洗后的 Parquet 文件...")
# 为绕过 CentOS 7 GLIBC 冲突，使用之前通过 hdfs dfs -get 下载到本地的路径
df = pd.read_parquet("/root/local_predictions")
raw_df = pd.read_parquet("/root/local_cleaned_data")

# 将原始波形数据与预测结果按时间戳进行内部合并
merged_df = pd.merge(raw_df, df[['timestamp', 'prediction']], on='timestamp', how='inner')

print("🚀 [2/3] 正在连接 HBase Thrift 服务...")
# 连接本机的 Thrift 服务 (端口 9090)
connection = happybase.Connection('127.0.0.1', port=9090)
table = connection.table('sensor_wave')

print("🚀 [3/3] 开始将数据高频写入 HBase (使用批量提交提升性能)...")
count = 0
# 开启批量写入 (Batch)，极大提升写入并发性能
with table.batch(batch_size=1000) as b:
    for index, row in merged_df.iterrows():
        # RowKey 设计策略：使用时间戳保证时序性
        row_key = str(row['timestamp']).encode('utf-8')
        
        # 组装宽表数据：必须转为字符串并 utf-8 编码
        data = {
            b'status:real': str(row['machine_status']).encode('utf-8'),
            b'status:pred': str(row['prediction']).encode('utf-8'),
            b'wave:s04': str(row['sensor_04']).encode('utf-8'), # 提取强特征：振动信号
            b'wave:s10': str(row['sensor_10']).encode('utf-8')  # 提取强特征：温度信号
        }
        b.put(row_key, data)
        
        count += 1
        if count % 10000 == 0:
            print(f"✅ 已成功写入 {count} 条波形记录...")

connection.close()
print("🎉 所有波形数据成功推入 HBase！前端可以开始毫秒级调用了。")