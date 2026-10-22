"""NPS 集成常量定义."""
DOMAIN = "nps"

# 轮询间隔（秒），可在集成的「配置」中修改
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 30

# 是否允许访问管理面板（由「管理面板访问」开关维护，持久化在配置条目选项里）
CONF_PANEL_ACCESS = "panel_access"
