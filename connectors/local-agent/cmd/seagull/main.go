package main

import (
	"os"

	"seagull/connectors/local-agent/internal/agentcli"
)

func main() {
	os.Exit(agentcli.Main(os.Args[1:], os.Stdout, os.Stderr, os.Environ(), nil))
}
