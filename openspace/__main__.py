import asyncio
import argparse
import sys
import logging
from typing import Optional

from openspace.tool_layer import OpenSpace, OpenSpaceConfig
from openspace.utils.logging import Logger
from openspace.utils.display import colorize

logger = Logger.get_logger(__name__)


async def _execute_task(openspace: OpenSpace, query: str):
    result = await openspace.execute(query)
    # Print summary
    status = result.get("status", "unknown")
    color = 'g' if status == "success" else 'rd'
    print(f"\n{colorize('Result:', 'c', bold=True)} {colorize(status, color)}")
    answer = result.get("answer", "")
    if answer:
        print(f"{answer[:500]}")
    return result


async def interactive_mode(openspace: OpenSpace):
    print(colorize("\nOpenSpace Interactive Mode", 'c', bold=True))
    print(colorize("Type 'exit' to quit, 'help' for commands.\n", 'gr'))

    while True:
        try:
            prompt = colorize(">>> ", 'c', bold=True)
            query = input(f"{prompt}").strip()

            if not query:
                continue
            if query.lower() in ('exit', 'quit', 'q'):
                print("\nExiting...")
                break
            if query.lower() == 'help':
                print("  exit/quit/q  - Exit interactive mode")
                print("  status       - Show system status")
                continue
            if query.lower() == 'status':
                backends = openspace.list_backends()
                print(f"  Model: {colorize(openspace.config.llm_model or '(not set)', 'c')}")
                print(f"  Backends: {colorize(', '.join(backends), 'c')}")
                continue

            await _execute_task(openspace, query)

        except KeyboardInterrupt:
            print("\n\nInterrupt signal detected, exiting...")
            break
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            print(f"\nError: {e}")


async def single_query_mode(openspace: OpenSpace, query: str):
    print(colorize(f"\nExecuting: {query}", 'c', bold=True))
    await _execute_task(openspace, query)


def _print_status(openspace: OpenSpace):
    """Print system status"""
    print(f"\n  Initialized: {openspace.is_initialized()}")
    print(f"  Running: {openspace.is_running()}")
    print(f"  Model: {openspace.config.llm_model or '(not set)'}")
    if openspace.is_initialized():
        backends = openspace.list_backends()
        print(f"  Backends: {', '.join(backends)}")
        sessions = openspace.list_sessions()
        print(f"  Active Sessions: {len(sessions)}")
    print()


def _create_argument_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser"""
    parser = argparse.ArgumentParser(
        description='OpenSpace - Self-Evolving Skill Worker & Community',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # refresh-cache subcommand
    cache_parser = subparsers.add_parser(
        'refresh-cache',
        help='Refresh MCP tool cache (starts all servers once)'
    )
    cache_parser.add_argument(
        '--config', '-c', type=str,
        help='MCP configuration file path'
    )
    
    # Basic arguments (for run mode)
    parser.add_argument('--config', '-c', type=str, help='Configuration file path (JSON format)')
    parser.add_argument('--query', '-q', type=str, help='Single query mode: execute query directly')
    
    # LLM arguments
    parser.add_argument('--model', '-m', type=str, help='LLM model name')
    
    # Logging arguments
    parser.add_argument('--log-level', type=str, choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Log level')
    
    # Execution arguments
    parser.add_argument('--max-iterations', type=int, help='Maximum iteration count')
    parser.add_argument('--timeout', type=float, help='LLM API call timeout (seconds)')

    return parser


async def refresh_mcp_cache(config_path: Optional[str] = None):
    """Refresh MCP tool cache by starting servers one by one and saving tool metadata."""
    from openspace.grounding.backends.mcp import MCPProvider, get_tool_cache
    from openspace.grounding.core.types import SessionConfig, BackendType
    from openspace.config import load_config, get_config
    
    print("Refreshing MCP tool cache...")
    print("Servers will be started one by one (start -> get tools -> close).")
    print()
    
    # Load config
    if config_path:
        config = load_config(config_path)
    else:
        config = get_config()
    
    # Get MCP config
    mcp_config = getattr(config, 'mcp', None) or {}
    if hasattr(mcp_config, 'model_dump'):
        mcp_config = mcp_config.model_dump()
    
    # Skip dependency checks for refresh-cache (servers are pre-validated)
    mcp_config["check_dependencies"] = False
    
    # Create provider
    provider = MCPProvider(config=mcp_config)
    await provider.initialize()
    
    servers = provider.list_servers()
    total = len(servers)
    print(f"Found {total} MCP servers configured")
    print()
    
    cache = get_tool_cache()
    cache.set_server_order(servers)  # Preserve config order when saving
    total_tools = 0
    success_count = 0
    skipped_count = 0
    failed_servers = []
    
    # Load existing cache to skip already processed servers
    existing_cache = cache.get_all_tools()
    
    # Timeout for each server (in seconds)
    SERVER_TIMEOUT = 60
    
    # Process servers one by one
    for i, server_name in enumerate(servers, 1):
        # Skip if already cached (resume support)
        if server_name in existing_cache:
            cached_tools = existing_cache[server_name]
            total_tools += len(cached_tools)
            skipped_count += 1
            print(f"[{i}/{total}] {server_name}... ⏭ cached ({len(cached_tools)} tools)")
            continue
        
        print(f"[{i}/{total}] {server_name}...", end=" ", flush=True)
        session_id = f"mcp-{server_name}"
        
        try:
            # Create session and get tools with timeout protection
            async with asyncio.timeout(SERVER_TIMEOUT):
                # Create session for this server
                cfg = SessionConfig(
                    session_name=session_id,
                    backend_type=BackendType.MCP,
                    connection_params={"server": server_name},
                )
                session = await provider.create_session(cfg)
                
                # Get tools from this server
                tools = await session.list_tools()
            
            # Convert to metadata format
            tool_metadata = []
            for tool in tools:
                tool_metadata.append({
                    "name": tool.schema.name,
                    "description": tool.schema.description or "",
                    "parameters": tool.schema.parameters or {},
                })
            
            # Save to cache (incremental)
            cache.save_server(server_name, tool_metadata)
            
            # Close session immediately to free resources
            await provider.close_session(session_id)
            
            total_tools += len(tools)
            success_count += 1
            print(f"✓ {len(tools)} tools")
        
        except asyncio.TimeoutError:
            error_msg = f"Timeout after {SERVER_TIMEOUT}s"
            failed_servers.append((server_name, error_msg))
            print(f"✗ {error_msg}")
            
            # Save failed server info to cache
            cache.save_failed_server(server_name, error_msg)
            
            # Try to close session if it was created
            try:
                await provider.close_session(session_id)
            except Exception:
                pass
            
        except Exception as e:
            error_msg = str(e)
            failed_servers.append((server_name, error_msg))
            print(f"✗ {error_msg[:50]}")
            
            # Save failed server info to cache
            cache.save_failed_server(server_name, error_msg)
            
            # Try to close session if it was created
            try:
                await provider.close_session(session_id)
            except Exception:
                pass
    
    print()
    print(f"{'='*50}")
    print(f"✓ Collected {total_tools} tools from {success_count + skipped_count}/{total} servers")
    if skipped_count > 0:
        print(f"  (skipped {skipped_count} cached, processed {success_count} new)")
    print(f"✓ Cache saved to: {cache.cache_path}")
    
    if failed_servers:
        print(f"✗ Failed servers ({len(failed_servers)}):")
        for name, err in failed_servers[:10]:
            print(f"  - {name}: {err[:60]}")
        if len(failed_servers) > 10:
            print(f"  ... and {len(failed_servers) - 10} more (see cache file for details)")
    
    print()
    print("Done! Future list_tools() calls will use cache (no server startup).")


def _load_config(args) -> OpenSpaceConfig:
    """Load configuration"""
    cli_overrides = {}
    if args.model:
        cli_overrides['llm_model'] = args.model
    if args.max_iterations is not None:
        cli_overrides['grounding_max_iterations'] = args.max_iterations
    if args.timeout is not None:
        cli_overrides['llm_timeout'] = args.timeout
    if args.log_level:
        cli_overrides['log_level'] = args.log_level

    try:
        if args.config:
            import json
            with open(args.config, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)
            config_dict.update(cli_overrides)
            config = OpenSpaceConfig(**config_dict)
            print(f"Loaded config: {args.config}")
        else:
            config = OpenSpaceConfig(**cli_overrides)

        if args.log_level:
            Logger.set_level(args.log_level)

        return config

    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)


async def _initialize_openspace(config: OpenSpaceConfig) -> OpenSpace:
    openspace = OpenSpace(config)
    print("Initializing OpenSpace...")
    await openspace.initialize()
    backends = openspace.list_backends()
    print(f"Ready. Backends: {', '.join(backends)}")
    return openspace


async def main():
    parser = _create_argument_parser()
    args = parser.parse_args()

    # Handle subcommands
    if args.command == 'refresh-cache':
        await refresh_mcp_cache(args.config)
        return 0

    # Load configuration
    config = _load_config(args)

    openspace = None

    try:
        openspace = await _initialize_openspace(config)

        if args.query:
            await single_query_mode(openspace, args.query)
        else:
            await interactive_mode(openspace)

    except KeyboardInterrupt:
        print("\n\nInterrupt signal detected")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        print(f"\nError: {e}")
        return 1
    finally:
        if openspace:
            print("\nCleaning up resources...")
            await openspace.cleanup()

    print("\nGoodbye!")
    return 0


def run_main():
    """Run main function"""
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nProgram interrupted")
        sys.exit(0)


if __name__ == "__main__":
    run_main()