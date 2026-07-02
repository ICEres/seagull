package main

import (
	"os"

	"seagull/packages/gulls/connect/local-agent/internal/agentcli"
)

func main() {
	os.Exit(agentcli.MainWithProgram("seagull", os.Args[1:], os.Stdout, os.Stderr, os.Environ(), nil))
}
