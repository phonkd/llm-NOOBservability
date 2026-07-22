# Minimal consumer flake: a NixOS host running llm-NOOBservability.
#
# Works against any Loki plus any Prometheus-compatible metrics API
# (Mimir with its /prometheus prefix, plain Prometheus without it) and any
# ollama server that has the configured model pulled.
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    llm-noobservability = {
      url = "github:phonkd/llm-NOOBservability";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { nixpkgs, llm-noobservability, ... }: {
    nixosConfigurations.myhost = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        llm-noobservability.nixosModules.default
        {
          services.noobservability = {
            enable = true;
            port = 8095;
            lokiUrl = "http://loki.example.internal:3100";
            # Plain Prometheus: drop the /prometheus prefix.
            mimirUrl = "http://mimir.example.internal:9009/prometheus";
            ollamaUrl = "http://ollama.example.internal:11434";
            model = "qwen3.5:9b";
            # Optional: teach the model your environment's conventions.
            extraContext = ''
              Journal logs live in service_name="journal"; select by unit + hostname.
            '';
          };
          networking.firewall.allowedTCPPorts = [ 8095 ];
        }
      ];
    };
  };
}
