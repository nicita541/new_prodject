"""CLI utility to inspect, shard-migrate, and prune DeepSeek response cache."""
import argparse
import sys
from pathlib import Path

# Ensure root is in sys.path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from app.deepseek import cache_stats, migrate_flat_cache, prune_cache, RESPONSES


def main():
    parser = argparse.ArgumentParser(description="DeepSeek response cache maintenance utility.")
    parser.add_argument("--stats", action="store_true", help="Print cache statistics only")
    parser.add_argument("--migrate", action="store_true", help="Migrate flat files into 2-char prefix shards")
    parser.add_argument("--prune", action="store_true", help="Prune corrupted and limit-exceeding cache files")
    parser.add_argument("--max-entries", type=int, default=20000, help="Maximum number of cache entries to retain")
    parser.add_argument("--max-mb", type=int, default=150, help="Maximum cache size in megabytes")
    parser.add_argument("--max-age-days", type=int, default=None, help="Maximum age in days before pruning")

    args = parser.parse_args()

    run_all = not (args.stats or args.migrate or args.prune)

    print(f"=== DeepSeek Cache Maintenance [{RESPONSES}] ===")
    initial_stats = cache_stats()
    print(f"Initial: {initial_stats['total_files']} files ({initial_stats['flat_files']} flat, "
          f"{initial_stats['sharded_files']} sharded across {initial_stats['shards_count']} shards), "
          f"{initial_stats['total_bytes'] / (1024*1024):.2f} MB")

    if args.stats and not (args.migrate or args.prune or run_all):
        return

    if args.migrate or run_all:
        print("\nMigrating flat files into 2-char prefix shards...")
        migration_res = migrate_flat_cache()
        print(f"Migration completed: {migration_res['migrated']} migrated, "
              f"{migration_res['skipped']} deduplicated, {migration_res['errors']} errors.")

    if args.prune or run_all:
        max_bytes = args.max_mb * 1024 * 1024
        print(f"\nPruning cache (max_entries={args.max_entries}, max_mb={args.max_mb}, max_age_days={args.max_age_days})...")
        prune_res = prune_cache(
            max_entries=args.max_entries,
            max_bytes=max_bytes,
            max_age_days=args.max_age_days,
            remove_corrupted=True,
        )
        print(f"Pruning completed: {prune_res['corrupted_removed']} corrupted removed, "
              f"{prune_res['expired_removed']} expired removed, {prune_res['limit_pruned']} limit-pruned, "
              f"{prune_res['remaining']} remaining.")

    final_stats = cache_stats()
    print(f"\nFinal: {final_stats['total_files']} files ({final_stats['flat_files']} flat, "
          f"{final_stats['sharded_files']} sharded across {final_stats['shards_count']} shards), "
          f"{final_stats['total_bytes'] / (1024*1024):.2f} MB")


if __name__ == "__main__":
    main()
