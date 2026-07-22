{ config, lib, pkgs, package }:
let
  cfg = config.services.noobservability;
in
{
  options.services.noobservability = {
    enable = lib.mkEnableOption "llm-NOOBservability NL observability querier";

    port = lib.mkOption {
      type = lib.types.port;
      default = 8095;
      description = "HTTP port for the API (and later the chat UI).";
    };

    lokiUrl = lib.mkOption {
      type = lib.types.str;
      default = "http://127.0.0.1:3100";
      description = "Base URL of Loki (no trailing slash).";
    };

    mimirUrl = lib.mkOption {
      type = lib.types.str;
      default = "http://127.0.0.1:9009/prometheus";
      description = "Prometheus-compatible base URL of Mimir, including the /prometheus prefix.";
    };

    ollamaUrl = lib.mkOption {
      type = lib.types.str;
      default = "http://127.0.0.1:11434";
      description = "Base URL of the ollama server used for NL -> query translation.";
    };

    model = lib.mkOption {
      type = lib.types.str;
      default = "qwen3.5:9b";
      description = "Ollama model tag used for query generation and summaries.";
    };

    extraContext = lib.mkOption {
      type = lib.types.lines;
      default = "";
      description = ''
        Environment-specific hints injected into the query-generation prompt
        (host naming, log label conventions, interesting metrics). Keeps the
        service itself environment-agnostic.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.noobservability = {
      description = "llm-NOOBservability NL observability querier";
      wantedBy = [ "multi-user.target" ];
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      environment = {
        NOOB_PORT = toString cfg.port;
        NOOB_LOKI_URL = cfg.lokiUrl;
        NOOB_MIMIR_URL = cfg.mimirUrl;
        NOOB_OLLAMA_URL = cfg.ollamaUrl;
        NOOB_MODEL = cfg.model;
        NOOB_EXTRA_CONTEXT_FILE =
          lib.mkIf (cfg.extraContext != "")
            (pkgs.writeText "noob-context.md" cfg.extraContext);
      };
      serviceConfig = {
        ExecStart = "${package}/bin/noob-server";
        DynamicUser = true;
        Restart = "on-failure";
        RestartSec = 5;
        # Read-only consumer of remote APIs; lock the unit down.
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
      };
    };
  };
}
