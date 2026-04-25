# 🔧 系统工程排错实战与知识库 (Troubleshooting)

本项目在开发过程中克服了大量底层操作系统、网络协议与组件依赖的工程挑战。以下为核心系统级瓶颈的排查与破局记录：

### 🚨 Issue 1: 底层 C 编译器缺失导致 Python 依赖构建失败
* **现象/报错：** `pip3 install numpy` 等科学计算包时直接抛出编译异常。
* **根因分析：** CentOS 基础精简版镜像未预装 C++ 编译套件，且 `pip` 版本过旧无法自动拉取预编译 Wheel 包。
* **解决方案：** 补充系统级编译器并升级包管理器。
  ```bash
  yum install -y gcc-c++
  /usr/local/python3/bin/pip3 install --upgrade pip
  ```

### 🚨 Issue 2: 基础网络探测工具缺失
* **现象/报错：** `bash: netstat: command not found`
* **根因分析：** 容器内缺少 `net-tools` 基础网络包，无法确认 Thrift 端口状态。
* **解决方案：**
  ```bash
  yum install -y net-tools
  ```

### 🚨 Issue 3: C 语言标准冲突阻断 thriftpy2 编译
* **现象/报错：** `error: ‘for’ loop initial declarations are only allowed in C99 mode`
* **根因分析：** 在安装 HBase 连接库 `happybase` 时，系统底层的 GCC 4.8 编译器默认沿用古老的 C89 标准，拒绝编译包含现代语法风格的依赖源码。
* **解决方案 (环境变量注入)：** 强制引导编译器采用 C99 新标准，越过系统编译墙。
  ```bash
  CFLAGS="-std=c99" /usr/local/python3/bin/pip3 install happybase -i [http://mirrors.pku.edu.cn/pypi/web/simple](http://mirrors.pku.edu.cn/pypi/web/simple) --trusted-host mirrors.pku.edu.cn
  ```

### 🚨 Issue 4: GLIBC 底层驱动版本严重不匹配
* **现象/报错：** `/lib64/libc.so.6: version 'GLIBC_2.25' not found`
* **根因分析：** 使用 `pyarrow` 试图让 Python 直连 HDFS 时，触发的 Hadoop 原生底层 C 库要求高版本 GLIBC，而 CentOS 7 核心库仅为 2.17，导致底层调用当场崩溃。
* **解决方案 (降级绕过策略)：** 放弃高风险的系统级内核升级。利用 Hadoop Shell 将目标文件拉取至本地容器沙箱，转而让 `pandas` 读取本地磁盘文件，完美规避网络驱动冲突。
  ```bash
  hdfs dfs -get /user/root/sensor_project/output/predictions /root/local_predictions
  hdfs dfs -get /user/root/sensor_project/output/cleaned_data /root/local_cleaned_data
  ```

### 🚨 Issue 5: Docker 虚拟网络物理隔离引发前端死锁
* **现象/报错：** Windows 启动大屏 `Lambda_Dashboard.py` 后无报错但界面不弹出，处于假死状态。
* **根因分析：** 容器集群初始化时仅暴漏了 9870、8088 端口。Hive (10000) 和 HBase (9090) 的 RPC 流量被死死封禁在容器内部虚拟网段 (`172.20.0.5`)，导致前端 UI 网络线程无期限阻塞。
* **解决方案 (物理层流量劫持)：** 借助网络流神器 `socat` 在宿主机强行建立物理监听，将请求流量“截胡”并 `fork` 入容器内部，打通跨网段屏障。同时关闭防火墙。
  ```bash
  systemctl stop firewalld
  socat TCP-LISTEN:9090,fork TCP:172.20.0.5:9090 &
  socat TCP-LISTEN:10000,fork TCP:172.20.0.5:10000 &
  ```

### 🚨 Issue 6: 时序数据耗尽导致波形静止
* **现象/报错：** 大屏展示数分钟后，HBase 波形图陷入停滞。
* **根因分析：** ODS 层灌入的 22 万条数据为“历史切片快照”，前端指针扫描到行尾后产生数据断层。
* **解决方案 (模拟流缓冲构建)：** 编写独立进程 `mock_sensor_stream.py` 充当工业网关，按照正态分布模型以 10Hz 的频次向 HBase 持续推送携带随机异常突变的新切片，保证前端大屏实现永久性的流式渲染体验。