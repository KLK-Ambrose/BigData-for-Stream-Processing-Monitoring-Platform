# 运行环境：master 容器（Spark 模型训练脚本）
# 执行命令：/usr/local/spark/bin/spark-submit /root/model_training.py
# 核心功能：读取清洗后的数据，进行特征向量化和标准化，训练随机森林分类模型（二分类），验证 AUC 分数，并保存带有 prediction 标签的数据。
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, when
from pyspark.ml.feature import VectorAssembler, StandardScaler
from pyspark.ml.classification import RandomForestClassifier
from pyspark.ml.evaluation import BinaryClassificationEvaluator

print("🚀 [1/6] 初始化 Spark 与加载 Parquet 数据...")
spark = SparkSession.builder.appName("SensorFailurePrediction").getOrCreate()
df = spark.read.parquet("hdfs://master:9000/user/root/sensor_project/output/cleaned_data")

print("🚀 [2/6] 重构标签：合并 BROKEN 和 RECOVERING 为异常状态(1)")
# 生成机器学习专属标签列：NORMAL 为 0，其他为 1
df = df.withColumn("label", when(col("machine_status") == "NORMAL", 0).otherwise(1))

print("🚀 [3/6] 特征工程：向量化与标准化")
# 自动提取所有传感器列名 (排除非特征列)
ignore_cols = ["timestamp", "machine_status", "label"]
feature_cols = [c for c in df.columns if c not in ignore_cols]

# 将多列组合成一个向量列 'raw_features'
assembler = VectorAssembler(inputCols=feature_cols, outputCol="raw_features")
df_assembled = assembler.transform(df)

# 标准化：消除物理量纲差异
scaler = StandardScaler(inputCol="raw_features", outputCol="features", withStd=True, withMean=True)
scaler_model = scaler.fit(df_assembled)
df_scaled = scaler_model.transform(df_assembled)

print("🚀 [4/6] 划分数据集：80% 用于训练，20% 用于测试...")
train_df, test_df = df_scaled.randomSplit([0.8, 0.2], seed=42)

print("🚀 [5/6] 正在训练 随机森林 (Random Forest) 模型...")
# 设置树的数量为20，最大深度为5 
rf = RandomForestClassifier(labelCol="label", featuresCol="features", numTrees=20, maxDepth=5, seed=42)
model = rf.fit(train_df)

print("🚀 [6/6] 模型训练完成！在测试集上进行验证...")
predictions = model.transform(test_df)
evaluator = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderROC")
auc = evaluator.evaluate(predictions)

print(f"==============================================")
print(f"🏆 模型评估完成！")
print(f"📊 测试集 AUC (Area Under ROC): {auc:.4f}")
print(f"==============================================")

# 将包含预测结果的数据保存，供后续 Hive 和前端可视化使用
output_path = "hdfs://master:9000/user/root/sensor_project/output/predictions"
print(f"💾 正在将带有预测标签的数据保存至: {output_path}")
predictions.select("timestamp", "machine_status", "label", "prediction").write.mode("overwrite").parquet(output_path)

spark.stop()