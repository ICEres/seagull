package main

import (
	"os"

	"seagull/packages/gulls/connect/local-agent/internal/agentcli"
)

func main() {
	os.Exit(agentcli.MainWithProgram("gulls", os.Args[1:], os.Stdout, os.Stderr, os.Environ(), nil))
}
