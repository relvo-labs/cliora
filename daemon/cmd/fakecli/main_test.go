package main

import "testing"

func TestPermissionPosture(t *testing.T) {
	for _, tc := range []struct {
		args                []string
		permission, sandbox string
	}{
		{nil, "cli_default", "enforced"},
		{[]string{autoPermissionFlag}, "auto", "enforced"},
		{[]string{sandboxBypassFlag}, "full_access", "bypassed"},
	} {
		permission, sandbox := permissionPosture(tc.args)
		if permission != tc.permission || sandbox != tc.sandbox {
			t.Errorf("args %v: permission=%s sandbox=%s", tc.args, permission, sandbox)
		}
	}
}
