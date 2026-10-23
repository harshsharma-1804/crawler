"""Synchronous server builder — ported from the reference crawler's s7_make_server.py.

Key design: flattened asset structure.
  assets/<domain>/css/shop/app.css  →  server/<domain>/shop/app.css
  (the css/ folder level is REMOVED; only the subfolder path below it is kept)

This exactly mirrors how the working reference crawler builds its server root,
which is the correct structure for serving the site offline.
"""

import shutil
from pathlib import Path


class SyncServerBuilder:
    """Build an offline server mirror with flattened asset paths."""

    def build(
        self,
        domain: str,
        html_root: Path,
        assets_root: Path,
        server_root: Path,
    ) -> Path:
        """Build the server structure for *domain*.

        Args:
            domain: Bare domain string, e.g. ``"aadhargupta.in"``.
            html_root: Root directory containing saved HTML files (e.g. ``data/project/htmls``).
            assets_root: Root directory containing downloaded assets (e.g. ``data/project/assets``).
            server_root: Destination root for the server mirror (e.g. ``data/server``).

        Returns:
            Path to the domain-specific server directory.
        """
        domain_folder = domain.replace(".", "_")

        html_src = html_root / domain_folder
        asset_src = assets_root / domain_folder
        server_domain_root = server_root / domain_folder

        # Reset destination
        if server_domain_root.exists():
            shutil.rmtree(server_domain_root)
        server_domain_root.mkdir(parents=True, exist_ok=True)

        print(f"\n[SyncServerBuilder] Building server for domain: {domain}")
        print(f"  html_src   = {html_src}")
        print(f"  asset_src  = {asset_src}")
        print(f"  server_dst = {server_domain_root}")

        # 1. Copy HTML tree (preserves routing structure exactly)
        if html_src.exists():
            self._copy_html_tree(html_src, server_domain_root)
        else:
            print(f"  ⚠ No HTML directory found at {html_src}")

        # 2. Merge assets with flattened structure
        self._copy_assets_flat(asset_src, server_domain_root)

        print(f"[SyncServerBuilder] ✅ Server build complete → {server_domain_root}")
        return server_domain_root

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _copy_html_tree(self, html_src: Path, server_domain_root: Path) -> None:
        """Copy HTML files preserving directory hierarchy (routing intact)."""
        copied = 0
        for item in html_src.rglob("*"):
            if item.is_dir():
                continue

            target = server_domain_root / item.relative_to(html_src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied += 1

        print(f"  ✔ HTML copied: {copied} file(s)")

    def _copy_assets_flat(self, asset_domain_root: Path, server_domain_root: Path) -> None:
        """Copy assets but REMOVE the asset-type folder level.

        Structure before:
            assets/<domain>/css/shop/style.css
            assets/<domain>/js/vendor/jquery.min.js
            assets/<domain>/images/logo.png

        Structure after (flattened):
            server/<domain>/shop/style.css
            server/<domain>/vendor/jquery.min.js
            server/<domain>/logo.png
        """
        if not asset_domain_root.exists():
            print(f"  ℹ️  No assets folder found — making empty assets folder at {asset_domain_root}")
            asset_domain_root.mkdir(parents=True, exist_ok=True)
            return

        total_copied = 0

        for asset_type_dir in asset_domain_root.iterdir():
            if not asset_type_dir.is_dir():
                continue

            asset_type_name = asset_type_dir.name
            type_count = 0

            for item in asset_type_dir.rglob("*"):
                if item.is_dir():
                    continue

                # relative_path is the path BELOW the asset type dir
                # e.g.  css/shop/style.css → relative_path = shop/style.css
                relative_path = item.relative_to(asset_type_dir)

                target = server_domain_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)

                # Don't overwrite (HTML files take priority over same-named assets)
                if not target.exists():
                    shutil.copy2(item, target)
                    type_count += 1
                else:
                    print(f"    [SKIP] {asset_type_name}: path collision, not overwriting → {relative_path}")

            if type_count:
                print(f"    ↳ {asset_type_name}: {type_count} file(s) merged")
            total_copied += type_count

        print(f"  ✔ Assets merged (flat): {total_copied} file(s)")
