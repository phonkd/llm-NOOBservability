{
  description = "llm-NOOBservability: natural-language Loki/Mimir querier";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      forAllSystems = f: nixpkgs.lib.genAttrs [ "x86_64-linux" "aarch64-darwin" ]
        (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (pkgs: rec {
        default = noobservability;
        noobservability = pkgs.python3Packages.buildPythonApplication {
          pname = "noobservability";
          version = "0.1.0";
          pyproject = true;
          src = ./.;
          build-system = [ pkgs.python3Packages.hatchling ];
          dependencies = with pkgs.python3Packages; [ fastapi httpx uvicorn ];
          # No network in the sandbox; tests run against live Loki/Mimir anyway.
          doCheck = false;
          meta = {
            description = "Natural-language observability querier for Loki/Mimir";
            homepage = "https://github.com/phonkd/llm-NOOBservability";
            license = pkgs.lib.licenses.mit;
            mainProgram = "noob";
          };
        };
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: with ps; [
              fastapi httpx uvicorn hatchling
              socksio # lets httpx honor ALL_PROXY=socks5:// for dev from the Mac
            ]))
          ];
        };
      });

      nixosModules.default = { config, lib, pkgs, ... }:
        import ./module.nix {
          inherit config lib pkgs;
          package = self.packages.${pkgs.system}.noobservability;
        };
    };
}
