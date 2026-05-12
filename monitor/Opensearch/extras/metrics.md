# HPE OpenSearch Performance Metrics — Stakeholder Guide

This guide provides a comprehensive overview of the metrics monitored within our OpenSearch environment. It is designed to help stakeholders understand how compute resources are being utilized, identify potential bottlenecks, and gain insights into cluster health.

---

## 1. Cluster Health Metrics
The overall health of the OpenSearch cluster determines data availability and system reliability.

### Cluster Status
- **Theory:** OpenSearch uses a color-coded system to represent health based on shard allocation.
- **Stakeholder Insight:**
    - **Green:** All data is fully protected and available. Operations are normal.
    - **Yellow:** All data is available, but some "backups" (replica shards) are missing. A single node failure could lead to data loss. This often happens during maintenance or when adding new nodes.
    - **Red:** Some primary data is unavailable. Searches will be incomplete and writes may fail. This requires **immediate** attention.

### Shard States (Active, Relocating, Initializing, Unassigned)
- **Theory:** Shards are the fundamental units of data storage. 
- **Stakeholder Insight:**
    - **Relocating/Initializing:** The cluster is moving data around (e.g., rebalancing after a node joins). This consumes network and disk bandwidth.
    - **Unassigned:** Data that isn't sitting on any node. If these are "Primary" shards, you have a **Red** status; if "Replica", it's **Yellow**.

### Pending Tasks
- **Theory:** A queue of cluster-level changes (like creating indices or updating mapping).
- **Stakeholder Insight:** A high number of pending tasks indicates the "Brain" (Master node) is overloaded. This can lead to the cluster becoming unresponsive to management commands.

---

## 2. Node Resource Utilization
These metrics show exactly what is "eating up" your compute resources on a per-node basis.

### CPU Utilization
- **Theory:** Measures the processing power used by OpenSearch for indexing (writing) and searching (reading).
- **Stakeholder Insight:** Consistently high CPU (>80%) usually means the workload is "Compute-Bound."
    - **Cause:** Heavy complex queries, high ingestion rates, or background data merging.
    - **Prevention:** Optimize queries, increase the number of nodes, or use faster processors.

### JVM Heap Usage
- **Theory:** OpenSearch runs on Java. The "Heap" is the dedicated memory for its internal operations.
- **Stakeholder Insight:** This is arguably the **most critical** memory metric.
    - **Warning/Critical:** If the heap reaches 75% or 90%, the system spends more time "Cleaning" memory (Garbage Collection) than doing work, leading to massive slowdowns or "Out of Memory" crashes.
    - **Prevention:** Avoid extremely large queries, reduce shard counts, or increase the RAM allocated to the OpenSearch process.

### Disk Usage & Watermarks
- **Theory:** The physical storage occupied by your logs and metrics.
- **Stakeholder Insight:** OpenSearch has "Watermarks" (limits).
    - **85% (Low):** No new shards will be allocated to the node.
    - **90% (High):** OpenSearch will try to move existing shards away.
    - **95% (Flood):** The index becomes **Read-Only**. No more data can be written.
    - **Prevention:** Implement data retention policies (deleting old logs) or expand storage capacity.

---

## 3. Storage & I/O Performance
How efficiently data is written to and read from the underlying hardware.

### IO_TotWait (I/O Wait)
- **Theory:** The percentage of time the CPU is sitting idle because it's waiting for the disk to respond.
- **Stakeholder Insight:** High IO Wait means your disks are too slow for the amount of data you're trying to process. Even if CPU usage looks low, the system will feel "laggy."
- **Cause:** Slow hardware or too many simultaneous read/write operations.

### Disk Utilization (% Busy)
- **Theory:** Measures how "saturated" the storage bandwidth is.
- **Stakeholder Insight:** If this is near 100%, the disk is doing as much work as it possibly can. Adding more data will directly increase latency for every user.

---

## 4. Ingestion & Search Activity
The actual "work" being performed by the system.

### Indexing Rate (Indexing Ops)
- **Theory:** The number of documents being written to the cluster per second.
- **Stakeholder Insight:** This tells you the volume of incoming data (e.g., logs from your applications). Sudden spikes in indexing rate can drive up CPU and Disk usage.

### Search Rate (Query Total)
- **Theory:** The volume of search requests being executed.
- **Stakeholder Insight:** High search rates consume memory and CPU. If search performance is slow while the rate is high, you may need more "Replica" shards to spread the load across more nodes.

---

## 5. Pipeline Health (Data Streams)
Metrics related to the flow of data from your sources into OpenSearch.

### Last Data Received (Maximum Timestamp)
- **Theory:** The age of the most recent document in a data stream.
- **Stakeholder Insight:** 
    - **Stale Data:** If a stream shows "1h ago" or "4h ago," it means your monitoring pipeline (Logstash/Kafka) has likely failed.
    - **Prevention:** This is an "Early Warning" system. If the pipeline is stuck, you aren't seeing real-time issues in your applications.

---

## Summary Checklist for Stakeholders

| Symptom | Likelty Culprit | Recommended Action |
| :--- | :--- | :--- |
| **Slow Searches** | High JVM Heap or Disk I/O | Check for "heavy" queries or slow storage. |
| **Data Not Updating** | High Max Timestamp (Stale) | Investigate Logstash/Kafka/Beats. |
| **Index is Read-Only** | Disk > 95% | Delete old indices or add disk space. |
| **Cluster "Flaky"** | High Pending Tasks | Reduce index creation frequency. |
| **Crashes/Restarts** | JVM Heap > 90% | Increase Heap size or reduce data kept in memory. |
