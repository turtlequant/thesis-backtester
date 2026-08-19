# Windows 打包与发布

项目使用 Nuitka 的 `standalone` 模式生成可移植 Windows 目录，并可自动压缩为 ZIP。发布包不是安装器：程序资源与可迁移的 `workspace/` 分离，工作区中的框架、算子、因子、筛选策略、报告和数据库可以整体备份。

## 为什么不用 onefile

应用包含 Pandas、Polars、AKShare、Matplotlib、pywebview 和本地研究资产，且会持续写入数据库、配置和报告。目录版启动更快、故障更容易定位，也不会把资源和用户数据误放进 onefile 的临时解压目录。

## 构建环境

- Windows x64
- uv-managed CPython 3.11（脚本会自动安装，并创建独立构建环境）
- uv
- 可用的 C 编译工具链；Nuitka 会按其支持策略使用本机 MSVC 或下载 MinGW64

构建依赖单独放在 `build` dependency group，不进入应用的正式运行依赖。

## 构建命令

```powershell
# 完整重建、运行发布包自检并生成 ZIP
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Clean

# 在同一次构建中额外生成经过脱敏的私有 Tushare 基线包
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Clean -PrivateBaseline

# 调试构建：保留控制台并暂不压缩
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Clean -ShowConsole -SkipArchive
```

脚本不会复用日常开发的 `.venv`。它通过 `uv python install 3.11` 准备 uv-managed CPython，并把锁定依赖同步到 `.build/packaging-venv`，再执行：

```text
.build/packaging-venv/Scripts/python.exe -m nuitka --standalone ... src/desktop/main.py
```

无需先全局安装 Nuitka。`uv.lock` 固定构建工具和应用依赖版本。

## 产物

```text
.build/nuitka/                         # Nuitka 中间文件和 compilation-report.xml
dist/ThesisBacktester-<stage>-v<version>-windows-x64/
├── ThesisBacktester.exe
├── *.dll / *.pyd                      # Python 与第三方运行库
├── src/desktop/frontend/              # 本地 Vue 页面和 vendor 依赖
├── resources/workspace_seed/           # 只读的初始研究资产
├── workspace/                          # 首次自检生成的可迁移研究工作区
│   ├── data/                           # 数据库、配置、对话和任务状态
│   ├── operators/                      # v1 与 v2 算子
│   ├── factors/                        # 声明式定义与兼容因子
│   ├── screening_strategies/           # 数值筛选策略
│   └── strategies/                     # 框架、报告与回测产物
├── docs/PRODUCT_GUIDE.md
├── README.md
├── LICENSE
└── BUILD_INFO.json

dist/ThesisBacktester-<stage>-v<version>-windows-x64.zip
dist/ThesisBacktester-<stage>-v<version>-private-baseline-windows-x64.zip
```

标准包不包含构建机上的数据库、历史报告、自定义框架和其他运行结果；其中的 `workspace/` 只由初始模板生成。私有基线包以同一标准程序为底座，另外加入 Tushare 历史数据库、当前研究资产、报告、回测结果、对话和非敏感设置。它明确排除 BaoStock 数据、`.env`、SQLite 临时日志，并清空 Tushare Token、LLM API Key 和局域网凭据，同时关闭自动更新。

私有基线包仅用于个人备份和内部迁移，不作为 GitHub 或其他公开渠道的数据发行包。

## 构建脚本做了什么

1. 从 `src/version.py` 读取应用名称、发布阶段和版本，用于界面、API、Python 包元数据、发布目录、压缩包和 `BUILD_INFO.json`。日常发布只需修改该文件中的 `__version__`；需要切换发布阶段时再修改 `RELEASE_STAGE`。
2. 使用 Matplotlib 无界面后端和显式 WinForms 模块执行 Nuitka standalone 编译，并补齐 AKShare 的包内日历数据。
3. 将正式内置研究资产写入 `resources/workspace_seed/`；排除本地数据库、报告、缓存和测试占位算子。
4. 检查关键文件是否齐全。
5. 运行 `ThesisBacktester.exe --runtime-check`，验证主要依赖和 WinForms 后端能否导入。
6. 自检通过后生成标准 ZIP 和 `BUILD_INFO.json`。
7. 使用 SQLite 在线备份制作一致的 Tushare 数据快照，在临时目录完成凭据脱敏和泄漏校验，再生成支持大文件的 ZIP64 私有基线包。

## 发布前检查

- 在未安装 Python 的干净 Windows x64 环境解压运行。
- 验证桌面窗口和 `http://127.0.0.1:18721` 都能打开。
- 分别检查 BaoStock、Tushare Token 和 AKShare 即时分析入口。
- 完成一次数据初始化、截面选股和不调用 LLM 的历史验证。
- 配置测试 LLM，完成一次短框架分析。
- 确认重启后 `workspace/` 中的框架、报告、配置和任务状态仍存在。
- 对正式公开发布的 EXE 与安装载体执行代码签名和恶意软件扫描。

## 工作区与数据目录覆盖

便携版默认使用 EXE 同级的 `workspace/`。可以通过 `.env` 或系统环境变量移动整个工作区：

```text
THESIS_BACKTESTER_WORKSPACE_DIR=D:\ThesisBacktesterWorkspace
```

也可以只移动体积较大的 `workspace/data/`：

```text
THESIS_BACKTESTER_DATA_DIR=D:\ThesisBacktesterData
```

工作区相对路径以 EXE 所在目录为基准；数据目录相对路径以工作区为基准。升级和备份应以完整工作区为单位。
