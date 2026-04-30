import os
import platform
import tarfile
import zipfile
import tempfile
import shutil
from typing import Any, List, Dict, Tuple
from pathlib import Path
from datetime import datetime, timedelta

import pytz
import psutil
import requests
from ruamel.yaml import YAML
from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.scalarstring import PreservedScalarString, DoubleQuotedScalarString
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.plugins import _PluginBase


class MediaWarp(_PluginBase):
    # 插件名称
    plugin_name = "MediaWarp Plus"
    # 插件描述
    plugin_desc = "Emby/Jellyfin/飞牛影视中间件：优化播放 Strm 文件、自定义前端样式、自定义允许访问客户端、嵌入脚本。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/refs/heads/main/icons/cloud.png"
    # 插件版本
    plugin_version = "1.2.12"
    # 插件作者
    plugin_author = "SR"
    # 作者主页
    author_url = "https://github.com/AkimioJR/MediaWarp"
    # 插件配置项ID前缀
    plugin_config_prefix = "mediawarp1_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    _mediaserver_helper = None
    _mediaserver = None
    _mediaservers = None
    _emby_server = None
    _emby_host = None
    _emby_apikey = None
    _scheduler = None
    process = None
    
    # === 基础及系统设置 ===
    _enabled = False
    _port = "9000"
    _custom_version = "0.2.3"
    _force_clean = False
    
    _log_access_console = True
    _log_access_file = False
    _log_service_console = True
    _log_service_file = False
    
    _cache_enable = False
    _cache_http_strm_ttl = "1m"
    _cache_alist_api_ttl = "10m"
    _cache_image_ttl = "10m"
    _cache_subtitle_ttl = "2h"
    
    # === HTTP Strm ===
    _http_strm_enable = False
    _http_strm_proxy = False
    _http_strm_final_url = True
    _http_strm_compatibility_mode = False
    _http_strm_prefix_list = "/media/strm/http\n/media/strm/https"
    
    # === Alist Strm ===
    _alist_enable = False
    _alist_proxy = True
    _alist_raw_url = False
    _alist_list = "- addr: http://192.168.1.100:5244\n  username: admin\n  password: adminadmin\n  prefix_list:\n    - /media/strm/MyAlist\n    - /mnt/cd2/strm\n- addr: https://xiaoya.com\n  token: xxxxxxx\n  prefix_list: \n    - /media/strm"
    
    # === Web UI ===
    _web_enable = False
    _web_custom = False
    _web_index = False
    _web_head = "<script src=\"/MediaWarp/custom/emby-front-end-mod/actor-plus.js\"></script>\n<script src=\"/MediaWarp/custom/emby-front-end-mod/emby-swiper.js\"></script>\n<script src=\"/MediaWarp/custom/emby-front-end-mod/emby-tab.js\"></script>\n<script src=\"/MediaWarp/custom/emby-front-end-mod/fanart-show.js\"></script>\n<script src=\"/MediaWarp/custom/emby-front-end-mod/playbackRate.js\"></script>"
    _web_robots = "User-agent: *\nDisallow: /"
    _crx = False
    _actor_plus = True
    _fanart_show = False
    _external_player_url = False
    _danmaku = False
    _video_together = False
    
    # === 客户端过滤 ===
    _client_enable = False
    _client_mode = "BlackList"
    _client_list = "Fileball\nInfuse"
    
    # === 字幕设置 ===
    _subtitle_enable = False
    _srt2ass = True
    _ass_style = "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,楷体,20,&H03FFFFFF,&H00FFFFFF,&H00000000,&H02000000,-1,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1"

    def __init__(self):
        super().__init__()
        class_name = self.__class__.__name__.lower()
        exe_name = "MediaWarp.exe" if platform.system().lower() == "windows" else "MediaWarp"
        self.__mediawarp_path = settings.PLUGIN_DATA_PATH / class_name / exe_name
        self.__config_path = settings.PLUGIN_DATA_PATH / class_name / "config"
        self.__logs_dir = settings.PLUGIN_DATA_PATH / class_name / "logs"
        self.__config_filename = "config.yaml"
        self.__mediawarp_version_path = settings.PLUGIN_DATA_PATH / class_name / "version.txt"

    def init_plugin(self, config: dict = None):
        self._mediaserver_helper = MediaServerHelper()
        self._mediaserver = None

        if config:
            self._enabled = config.get("enabled", False)
            self._port = config.get("port", "9000")
            self._mediaservers = config.get("mediaservers", [])
            self._custom_version = config.get("custom_version", "0.2.3")
            self._force_clean = config.get("force_clean", False)
            
            self._log_access_console = config.get("log_access_console", True)
            self._log_access_file = config.get("log_access_file", False)
            self._log_service_console = config.get("log_service_console", True)
            self._log_service_file = config.get("log_service_file", False)
            
            self._cache_enable = config.get("cache_enable", False)
            self._cache_http_strm_ttl = config.get("cache_http_strm_ttl", "1m")
            self._cache_alist_api_ttl = config.get("cache_alist_api_ttl", "10m")
            self._cache_image_ttl = config.get("cache_image_ttl", "10m")
            self._cache_subtitle_ttl = config.get("cache_subtitle_ttl", "2h")
            
            self._http_strm_enable = config.get("http_strm_enable", False)
            self._http_strm_proxy = config.get("http_strm_proxy", False)
            self._http_strm_final_url = config.get("http_strm_final_url", True)
            self._http_strm_compatibility_mode = config.get("http_strm_compatibility_mode", False)
            self._http_strm_prefix_list = config.get("http_strm_prefix_list", self._http_strm_prefix_list)
            
            self._alist_enable = config.get("alist_enable", False)
            self._alist_proxy = config.get("alist_proxy", True)
            self._alist_raw_url = config.get("alist_raw_url", False)
            self._alist_list = config.get("alist_list", self._alist_list)
            
            self._web_enable = config.get("web_enable", False)
            self._web_custom = config.get("web_custom", False)
            self._web_index = config.get("web_index", False)
            self._web_head = config.get("web_head", self._web_head)
            self._web_robots = config.get("web_robots", self._web_robots)
            self._crx = config.get("crx", False)
            self._actor_plus = config.get("actor_plus", True)
            self._fanart_show = config.get("fanart_show", False)
            self._external_player_url = config.get("external_player_url", False)
            self._danmaku = config.get("danmaku", False)
            self._video_together = config.get("video_together", False)
            
            self._client_enable = config.get("client_enable", False)
            self._client_mode = config.get("client_mode", "BlackList")
            self._client_list = config.get("client_list", self._client_list)
            
            self._subtitle_enable = config.get("subtitle_enable", False)
            self._srt2ass = config.get("srt2ass", True)
            self._ass_style = config.get("ass_style", self._ass_style)

            if self._mediaservers:
                self._mediaserver = [self._mediaservers[0]]

        if self._mediaserver:
            emby_servers = self._mediaserver_helper.get_services(name_filters=self._mediaserver)
            for _, emby_server in emby_servers.items():
                self._emby_server = emby_server.type
                self._emby_apikey = emby_server.config.config.get("apikey")
                self._emby_host = emby_server.config.config.get("host")
                if self._emby_host and self._emby_host.endswith("/"):
                    self._emby_host = self._emby_host.rstrip("/")
                if self._emby_host and not self._emby_host.startswith("http"):
                    self._emby_host = "http://" + self._emby_host

        self.stop_service()

        if self._force_clean:
            logger.info("检测到重装命令，正在强制清理旧的 MediaWarp 核心与配置...")
            self.clean_old_files()
            self._force_clean = False
            logger.info("清理完成，正在自动将 UI 重装开关归位...")
            self.__update_config()

        if self._enabled:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            logger.info("MediaWarp 服务启动中...")
            self._scheduler.add_job(
                func=self.__run_service,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=2),
                name="MediaWarp启动服务",
            )
            if self._scheduler.get_jobs():
                self._scheduler.start()

    def clean_old_files(self):
        try:
            if os.path.exists(self.__mediawarp_path):
                os.remove(self.__mediawarp_path)
            if os.path.exists(self.__config_path):
                shutil.rmtree(self.__config_path, ignore_errors=True)
            if os.path.exists(self.__mediawarp_version_path):
                os.remove(self.__mediawarp_version_path)
            logger.info("✅ MediaWarp 旧核心与配置文件已清理完毕")
        except Exception as e:
            logger.error(f"清理旧文件时发生错误（可能存在系统占用）: {e}")

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "port": self._port,
            "mediaservers": self._mediaservers,
            "custom_version": self._custom_version,
            "force_clean": False, 
            
            "log_access_console": self._log_access_console,
            "log_access_file": self._log_access_file,
            "log_service_console": self._log_service_console,
            "log_service_file": self._log_service_file,
            
            "cache_enable": self._cache_enable,
            "cache_http_strm_ttl": self._cache_http_strm_ttl,
            "cache_alist_api_ttl": self._cache_alist_api_ttl,
            "cache_image_ttl": self._cache_image_ttl,
            "cache_subtitle_ttl": self._cache_subtitle_ttl,
            
            "http_strm_enable": self._http_strm_enable,
            "http_strm_proxy": self._http_strm_proxy,
            "http_strm_final_url": self._http_strm_final_url,
            "http_strm_compatibility_mode": self._http_strm_compatibility_mode,
            "http_strm_prefix_list": self._http_strm_prefix_list,
            
            "alist_enable": self._alist_enable,
            "alist_proxy": self._alist_proxy,
            "alist_raw_url": self._alist_raw_url,
            "alist_list": self._alist_list,
            
            "web_enable": self._web_enable,
            "web_custom": self._web_custom,
            "web_index": self._web_index,
            "web_head": self._web_head,
            "web_robots": self._web_robots,
            "crx": self._crx,
            "actor_plus": self._actor_plus,
            "fanart_show": self._fanart_show,
            "external_player_url": self._external_player_url,
            "danmaku": self._danmaku,
            "video_together": self._video_together,
            
            "client_enable": self._client_enable,
            "client_mode": self._client_mode,
            "client_list": self._client_list,
            
            "subtitle_enable": self._subtitle_enable,
            "srt2ass": self._srt2ass,
            "ass_style": self._ass_style,
        })

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_page(self) -> List[dict]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        tab_http = [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "http_strm_enable", "label": "启用 HTTP Strm"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "http_strm_proxy", "label": "流量代理 (允许转码)"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "http_strm_final_url", "label": "解析直链 (减少重定向)"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "http_strm_compatibility_mode", "label": "低效兼容模式"}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextarea", "props": {"model": "http_strm_prefix_list", "label": "Prefix List 挂载前缀 (一行一个)", "rows": 3, "hint": "按行填写挂载目录前缀", "persistent-hint": True}}]},
            ]}
        ]

        tab_alist = [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "alist_enable", "label": "启用 Alist Strm"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "alist_proxy", "label": "流量代理 (允许转码)"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "alist_raw_url", "label": "响应上游直链 (Raw URL)"}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextarea", "props": {"model": "alist_list", "label": "Alist 服务器列表 (YAML格式)", "rows": 12, "hint": "必须严格按照YAML缩进格式填写", "persistent-hint": True}}]},
            ]}
        ]

        tab_web = [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "web_enable", "label": "总开关 (启用 Web 修改)"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "web_custom", "label": "加载自定义静态资源"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "VSwitch", "props": {"model": "web_index", "label": "从 custom 读取 index.html"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "crx", "label": "CRX 美化"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "actor_plus", "label": "头像过滤"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "fanart_show", "label": "显示同人图"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "external_player_url", "label": "Emby 外置播放器"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "danmaku", "label": "Web弹幕"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "video_together", "label": "共同观影"}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextarea", "props": {"model": "web_head", "label": "注入 index.html 头部代码", "rows": 6}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextarea", "props": {"model": "web_robots", "label": "自定义 robots.txt", "rows": 6}}]},
            ]}
        ]

        tab_sub = [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VSwitch", "props": {"model": "subtitle_enable", "label": "启用字幕拦截处理"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VSwitch", "props": {"model": "srt2ass", "label": "SRT 强制转 ASS 字幕"}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextarea", "props": {"model": "ass_style", "label": "自定义 ASS 样式覆盖 (一行一个)", "rows": 4, "hint": "不需要加双引号，系统会自动为你添加双引号格式", "persistent-hint": True}}]},
            ]}
        ]

        tab_client = [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VSwitch", "props": {"model": "client_enable", "label": "启用客户端过滤"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VSelect", "props": {"model": "client_mode", "label": "过滤模式", "items": [{"title": "黑名单 (BlackList)", "value": "BlackList"}, {"title": "白名单 (WhiteList)", "value": "WhiteList"}]}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VTextarea", "props": {"model": "client_list", "label": "过滤名单 (一行一个)", "rows": 4}}]},
            ]}
        ]

        tab_adv = [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "div", "text": "=== 缓存设置 ===", "class": "text-subtitle-1 font-weight-bold"}]},
                {"component": "VCol", "props": {"cols": 12, "md": 12}, "content": [{"component": "VSwitch", "props": {"model": "cache_enable", "label": "启用内存缓存"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "cache_http_strm_ttl", "label": "HTTP Strm 缓存时长"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "cache_alist_api_ttl", "label": "Alist API 缓存时长"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "cache_image_ttl", "label": "图片缓存时长"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "cache_subtitle_ttl", "label": "字幕缓存时长"}}]},
                
                {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "div", "text": "=== 日志设置 ===", "class": "text-subtitle-1 font-weight-bold mt-4"}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "log_access_console", "label": "Access 终端日志"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "log_access_file", "label": "Access 文件日志"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "log_service_console", "label": "Service 终端日志"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "log_service_file", "label": "Service 文件日志"}}]},
            ]},
        ]

        return [
            {
                "component": "VCard",
                "props": {"variant": "outlined", "class": "mb-3"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "props": {"class": "d-flex align-center"},
                        "content": [
                            {"component": "VIcon", "props": {"icon": "mdi-rocket-launch", "color": "primary", "class": "mr-2"}},
                            {"component": "span", "text": "MediaWarp Plus 核心设置"},
                        ],
                    },
                    {"component": "VDivider"},
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VRow",
                                "content": [
                                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启动中间件", "color": "success"}}]},
                                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "force_clean", "label": "清理并重下覆盖", "color": "error", "hint": "勾选后务必点击下方“保存”执行", "persistent-hint": True}}]},
                                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "custom_version", "label": "目标下载版本"}}]},
                                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VTextField", "props": {"model": "port", "label": "绑定服务端口"}}]},
                                    {"component": "VCol", "props": {"cols": 12, "md": 12}, "content": [{"component": "VSelect", "props": {"multiple": True, "chips": True, "clearable": True, "model": "mediaservers", "label": "代理目标媒体服务器", "items": [{"title": config.name, "value": config.name} for config in self._mediaserver_helper.get_configs().values() if config.type in ["emby", "jellyfin", "trimemedia"]]}}]},
                                ],
                            },
                        ],
                    },
                ],
            },
            {
                "component": "VCard",
                "props": {"variant": "outlined"},
                "content": [
                    {
                        "component": "VTabs",
                        "props": {"model": "tab", "grow": True, "color": "primary"},
                        "content": [
                            {"component": "VTab", "props": {"value": "http-strm"}, "content": [{"component": "VIcon", "props": {"icon": "mdi-link-variant", "start": True}}, {"component": "span", "text": "HTTP"} ]},
                            {"component": "VTab", "props": {"value": "alist-strm"}, "content": [{"component": "VIcon", "props": {"icon": "mdi-cloud-outline", "start": True}}, {"component": "span", "text": "Alist"} ]},
                            {"component": "VTab", "props": {"value": "web-ui"}, "content": [{"component": "VIcon", "props": {"icon": "mdi-monitor-dashboard", "start": True}}, {"component": "span", "text": "Web UI"} ]},
                            {"component": "VTab", "props": {"value": "subtitle"}, "content": [{"component": "VIcon", "props": {"icon": "mdi-format-text", "start": True}}, {"component": "span", "text": "字幕"} ]},
                            {"component": "VTab", "props": {"value": "client"}, "content": [{"component": "VIcon", "props": {"icon": "mdi-cellphone-link", "start": True}}, {"component": "span", "text": "客户端"} ]},
                            {"component": "VTab", "props": {"value": "adv"}, "content": [{"component": "VIcon", "props": {"icon": "mdi-cogs", "start": True}}, {"component": "span", "text": "高级"} ]},
                        ],
                    },
                    {"component": "VDivider"},
                    {
                        "component": "VWindow",
                        "props": {"model": "tab"},
                        "content": [
                            {"component": "VWindowItem", "props": {"value": "http-strm"}, "content": [{"component": "VCardText", "content": tab_http}]},
                            {"component": "VWindowItem", "props": {"value": "alist-strm"}, "content": [{"component": "VCardText", "content": tab_alist}]},
                            {"component": "VWindowItem", "props": {"value": "web-ui"}, "content": [{"component": "VCardText", "content": tab_web}]},
                            {"component": "VWindowItem", "props": {"value": "subtitle"}, "content": [{"component": "VCardText", "content": tab_sub}]},
                            {"component": "VWindowItem", "props": {"value": "client"}, "content": [{"component": "VCardText", "content": tab_client}]},
                            {"component": "VWindowItem", "props": {"value": "adv"}, "content": [{"component": "VCardText", "content": tab_adv}]},
                        ],
                    },
                ],
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mt-2",
                },
                "content": [
                    {
                        "component": "div",
                        "text": "非 Host 模式需手动映射端口。FNTV 默认端口为 8005，暂不支持流量代理及 Web 页面修改。",
                    },
                ],
            },
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mt-2",
                },
                "content": [
                    {
                        "component": "div",
                        "text": "Emby/Jellyfin/飞牛影视中间件：优化播放 Strm 文件、自定义前端样式、自定义允许访问客户端、嵌入脚本，推荐配合AutoFilm使用，交流群：https://t.me/AkimioJR_MediaWarp",
                    },
                ],
            },
        ], {
            "enabled": self._enabled, "port": self._port, "mediaservers": self._mediaservers, "custom_version": self._custom_version, "force_clean": False,
            "log_access_console": self._log_access_console, "log_access_file": self._log_access_file, "log_service_console": self._log_service_console, "log_service_file": self._log_service_file,
            "cache_enable": self._cache_enable, "cache_http_strm_ttl": self._cache_http_strm_ttl, "cache_alist_api_ttl": self._cache_alist_api_ttl, "cache_image_ttl": self._cache_image_ttl, "cache_subtitle_ttl": self._cache_subtitle_ttl,
            "http_strm_enable": self._http_strm_enable, "http_strm_proxy": self._http_strm_proxy, "http_strm_final_url": self._http_strm_final_url, "http_strm_compatibility_mode": self._http_strm_compatibility_mode, "http_strm_prefix_list": self._http_strm_prefix_list,
            "alist_enable": self._alist_enable, "alist_proxy": self._alist_proxy, "alist_raw_url": self._alist_raw_url, "alist_list": self._alist_list,
            "web_enable": self._web_enable, "web_custom": self._web_custom, "web_index": self._web_index, "web_head": self._web_head, "web_robots": self._web_robots, "crx": self._crx, "actor_plus": self._actor_plus, "fanart_show": self._fanart_show, "external_player_url": self._external_player_url, "danmaku": self._danmaku, "video_together": self._video_together,
            "client_enable": self._client_enable, "client_mode": self._client_mode, "client_list": self._client_list,
            "subtitle_enable": self._subtitle_enable, "srt2ass": self._srt2ass, "ass_style": self._ass_style,
            "tab": "http-strm",
        }

    def __run_service(self):
        if not Path(self.__mediawarp_path).exists():
            self.__download_and_extract()
            if not Path(self.__mediawarp_path).exists():
                logger.error("下载失败，MediaWarp 文件不存在，无法启动")
                return

        if os.path.exists(self.__mediawarp_version_path):
            with open(self.__mediawarp_version_path, "r", encoding="utf-8") as f:
                if f.read().strip() != self._custom_version:
                    self.__download_and_extract()
                    
        if not Path(self.__config_path / self.__config_filename).exists():
            self.__download_and_extract()

        alist_config_parsed = []
        if self._alist_list.strip():
            try:
                yml = YAML()
                parsed = yml.load(self._alist_list)
                if isinstance(parsed, list):
                    alist_config_parsed = parsed
            except Exception as e:
                logger.error(f"解析 Alist YAML 失败: {e}")

        head_val = self._web_head.replace('\r\n', '\n')
        robots_val = self._web_robots.replace('\r\n', '\n')

        ass_styles_parsed = []
        for line in self._ass_style.split("\n"):
            line = line.strip()
            if line:
                if line.startswith('"') and line.endswith('"'):
                    line = line[1:-1]
                elif line.startswith("'") and line.endswith("'"):
                    line = line[1:-1]
                ass_styles_parsed.append(DoubleQuotedScalarString(line))

        changes = {
            "port": int(self._port) if self._port else 9000,
            
            "log.access.console": bool(self._log_access_console),
            "log.access.file": bool(self._log_access_file),
            "log.service.console": bool(self._log_service_console),
            "log.service.file": bool(self._log_service_file),
            
            "cache.enable": bool(self._cache_enable),
            "cache.http_strm_ttl": self._cache_http_strm_ttl,
            "cache.alist_api_ttl": self._cache_alist_api_ttl,
            "cache.image_ttl": self._cache_image_ttl,
            "cache.subtitle_ttl": self._cache_subtitle_ttl,
            
            "web.enable": bool(self._web_enable),
            "web.custom": bool(self._web_custom),
            "web.index": bool(self._web_index),
            "web.head": PreservedScalarString(head_val) if head_val else "",
            "web.robots": PreservedScalarString(robots_val) if robots_val else "",
            "web.crx": bool(self._crx),
            "web.actor_plus": bool(self._actor_plus),
            "web.fanart_show": bool(self._fanart_show),
            "web.external_player_url": bool(self._external_player_url),
            "web.danmaku": bool(self._danmaku),
            "web.video_together": bool(self._video_together),
            
            "client.enable": bool(self._client_enable),
            "client.mode": self._client_mode,
            "client.list": [p.strip() for p in self._client_list.split("\n") if p.strip()] if self._client_list else [],
            
            "http_strm.enable": bool(self._http_strm_enable),
            "http_strm.proxy": bool(self._http_strm_proxy),
            "http_strm.final_url": bool(self._http_strm_final_url),
            "http_strm.compatibility_mode": bool(self._http_strm_compatibility_mode),
            "http_strm.prefix_list": [p.strip() for p in self._http_strm_prefix_list.split("\n") if p.strip()] if self._http_strm_prefix_list else [],
            
            "alist_strm.enable": bool(self._alist_enable),
            "alist_strm.proxy": bool(self._alist_proxy),
            "alist_strm.raw_url": bool(self._alist_raw_url),
            "alist_strm.list": alist_config_parsed,
            
            "subtitle.enable": bool(self._subtitle_enable),
            "subtitle.art2ass": bool(self._srt2ass),
            "subtitle.srt2ass": bool(self._srt2ass),
            "subtitle.ass_style": ass_styles_parsed,
        }
        
        if self._emby_host:
            if self._emby_server == "jellyfin":
                changes["server.type"] = "Jellyfin"
            elif self._emby_server == "trimemedia":
                changes["server.type"] = "FNTV"
            else:
                changes["server.type"] = "Emby"
                
            changes["server.addr"] = self._emby_host
            if self._emby_apikey and self._emby_server != "trimemedia":
                changes["server.auth"] = self._emby_apikey
        
        self.__modify_config(Path(self.__config_path / self.__config_filename), changes)

        Path(self.__config_path).mkdir(parents=True, exist_ok=True)
        Path(self.__logs_dir).mkdir(parents=True, exist_ok=True)

        working_dir = settings.PLUGIN_DATA_PATH / self.__class__.__name__.lower()
        self.process = psutil.Popen([str(self.__mediawarp_path)], cwd=str(working_dir))

        if self.process.is_running():
            logger.info("MediaWarp Plus 服务成功启动！")

    def __modify_config(self, config_path, modifications):
        if not os.path.exists(config_path):
            logger.error(f"配置文件缺失，跳过写入: {config_path}")
            return
            
        yaml = YAML()
        yaml.preserve_quotes = True 
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.width = 4096

        def represent_bool(self, data):
            if data:
                return self.represent_scalar("tag:yaml.org,2002:bool", "true")
            else:
                return self.represent_scalar("tag:yaml.org,2002:bool", "false")

        RoundTripRepresenter.add_representer(bool, represent_bool)

        with open(config_path, "r", encoding="utf-8") as file:
            config = yaml.load(file)

        for key, value in modifications.items():
            keys = key.split(".")
            current = config
            for k in keys[:-1]:
                current = current.setdefault(k, {})
            current[keys[-1]] = value

        with open(config_path, "w", encoding="utf-8") as file:
            yaml.dump(config, file)

    def __get_download_url(self):
        machine = platform.machine().lower()
        arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
        
        os_sys = platform.system().lower()
        if os_sys == "windows":
            os_name = "windows"
            ext = "zip"
        elif os_sys == "darwin":
            os_name = "darwin"
            ext = "tar.gz"
        else:
            os_name = "linux"
            ext = "tar.gz"
            
        return f"https://github.com/AkimioJR/MediaWarp/releases/download/v{self._custom_version}/MediaWarp_{self._custom_version}_{os_name}_{arch}.{ext}"

    def __get_config_url(self):
        return f"https://github.com/AkimioJR/MediaWarp/releases/download/v{self._custom_version}/config.yaml"

    def __download_and_extract(self):
        bin_url = self.__get_download_url()
        cfg_url = self.__get_config_url()
        temp_dir = tempfile.mkdtemp()
        
        is_zip = bin_url.endswith(".zip")
        temp_file = os.path.join(temp_dir, "MediaWarp.zip" if is_zip else "MediaWarp.tar.gz")

        try:
            Path(self.__config_path).mkdir(parents=True, exist_ok=True)
            logger.info(f"正在下载 MediaWarp: {bin_url}")
            response = requests.get(bin_url, stream=True, proxies=settings.PROXY)
            response.raise_for_status()

            with open(temp_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            logger.info("正在解压...")
            exe_target = "MediaWarp.exe" if is_zip else "MediaWarp"
            
            if is_zip:
                with zipfile.ZipFile(temp_file, "r") as zip_ref:
                    mediawarp_member = [m for m in zip_ref.namelist() if m.endswith(exe_target)]
                    if mediawarp_member:
                        zip_ref.extract(mediawarp_member[0], path=temp_dir)
                        extracted_path = Path(temp_dir) / mediawarp_member[0]
                        shutil.copy2(extracted_path, Path(self.__mediawarp_path))
            else:
                with tarfile.open(temp_file, "r:gz") as tar:
                    mediawarp_member = [m for m in tar.getmembers() if m.name.endswith(exe_target)]
                    if mediawarp_member:
                        tar.extract(member=mediawarp_member[0], path=temp_dir)
                        extracted_path = Path(temp_dir) / mediawarp_member[0].name
                        extracted_path.chmod(0o755)
                        shutil.copy2(extracted_path, Path(self.__mediawarp_path))

            config_target = Path(self.__config_path / self.__config_filename)
            if not config_target.exists():
                logger.info(f"正在下载官方配置文件: {cfg_url}")
                cfg_resp = requests.get(cfg_url, proxies=settings.PROXY, timeout=30)
                cfg_resp.raise_for_status()
                config_target.write_bytes(cfg_resp.content)

            with open(self.__mediawarp_version_path, "w", encoding="utf-8") as f:
                f.write(self._custom_version)
                
            logger.info("MediaWarp 下载与环境配置完毕！")
        except Exception as e:
            logger.error(f"下载文件时发生错误: {e}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def stop_service(self):
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
            if self.process:
                if self.process.is_running():
                    self.process.kill()
                    try:
                        self.process.wait(timeout=2)
                    except psutil.TimeoutExpired:
                        pass
                self.process = None
        except Exception as e:
            pass