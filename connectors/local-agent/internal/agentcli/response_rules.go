package agentcli

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"
)

const (
	SchemaVersion = "seagull.response_rules.v1"

	RuleSourceConnectorConfig = "connector_config"
	RuleSourceBuiltInDefaults = "built_in_defaults"

	OutcomeDraftReply = "draft_reply"
	OutcomeAskHuman   = "ask_human"
	OutcomeNoReply    = "no_reply"
)

type ResponseRules struct {
	SchemaVersion      string
	Persona            string
	Style              string
	ReplyPosture       string
	MaxReplyChars      int
	AskHumanTriggers   []string
	ProhibitedBehavior []string
}

type ResponseRuleResolution struct {
	Rules           ResponseRules
	Source          string
	ValidationError string
}

func (r ResponseRuleResolution) IsValid() bool {
	return r.ValidationError == ""
}

type DraftResult struct {
	Outcome       string
	Draft         string
	Reason        string
	AppliedRules  map[string]any
	TriggerLabels []string
}

func (r DraftResult) ToMap() map[string]any {
	result := map[string]any{
		"outcome":        r.Outcome,
		"reason":         r.Reason,
		"applied_rules":  r.AppliedRules,
		"trigger_labels": r.TriggerLabels,
	}
	if r.Draft != "" {
		result["draft"] = r.Draft
	}
	return result
}

func ResolveConnectorResponseRules(rulesFile string, rulesJSON string) ResponseRuleResolution {
	cleanedFile := cleanString(rulesFile)
	cleanedJSON := cleanString(rulesJSON)
	if cleanedFile != "" && cleanedJSON != "" {
		return invalidResolution("set only one of SEAGULL_RESPONSE_RULES_FILE or SEAGULL_RESPONSE_RULES_JSON")
	}
	if cleanedFile == "" && cleanedJSON == "" {
		return ResponseRuleResolution{Rules: DefaultResponseRules(), Source: RuleSourceBuiltInDefaults}
	}

	var raw map[string]any
	var err error
	if cleanedJSON != "" {
		raw, err = decodeJSONObject([]byte(cleanedJSON))
	} else {
		bytes, readErr := os.ReadFile(expandHome(cleanedFile))
		if readErr != nil {
			return invalidResolution(readErr.Error())
		}
		raw, err = decodeJSONObject(bytes)
	}
	if err != nil {
		return invalidResolution(err.Error())
	}

	rules, err := ValidateResponseRules(raw)
	if err != nil {
		return invalidResolution(err.Error())
	}
	return ResponseRuleResolution{Rules: rules, Source: RuleSourceConnectorConfig}
}

func decodeJSONObject(data []byte) (map[string]any, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var raw any
	if err := decoder.Decode(&raw); err != nil {
		return nil, err
	}
	object, ok := raw.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("response rules must be a JSON object")
	}
	return object, nil
}

func ValidateResponseRules(raw map[string]any) (ResponseRules, error) {
	allowed := map[string]bool{
		"schema_version":      true,
		"persona":             true,
		"style":               true,
		"reply_posture":       true,
		"max_reply_chars":     true,
		"ask_human_triggers":  true,
		"prohibited_behavior": true,
	}
	unknown := []string{}
	for field := range raw {
		if !allowed[field] {
			unknown = append(unknown, field)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return ResponseRules{}, fmt.Errorf("unknown response rule field(s): %s", strings.Join(unknown, ", "))
	}

	schemaVersion, err := requireString(raw, "schema_version")
	if err != nil {
		return ResponseRules{}, err
	}
	if schemaVersion != SchemaVersion {
		return ResponseRules{}, fmt.Errorf("schema_version must be %s", SchemaVersion)
	}

	persona, err := requireString(raw, "persona")
	if err != nil {
		return ResponseRules{}, err
	}
	style, err := requireString(raw, "style")
	if err != nil {
		return ResponseRules{}, err
	}
	replyPosture, err := requireString(raw, "reply_posture")
	if err != nil {
		return ResponseRules{}, err
	}
	if !known(replyPosture, []string{OutcomeDraftReply, OutcomeAskHuman, OutcomeNoReply}) {
		return ResponseRules{}, fmt.Errorf("reply_posture must be draft_reply, ask_human, or no_reply")
	}

	maxReplyChars, err := requireInt(raw, "max_reply_chars")
	if err != nil {
		return ResponseRules{}, err
	}
	if maxReplyChars < 1 || maxReplyChars > 4000 {
		return ResponseRules{}, fmt.Errorf("max_reply_chars must be between 1 and 4000")
	}

	askHumanTriggers, err := requireKnownStrings(raw, "ask_human_triggers", knownTriggerLabels())
	if err != nil {
		return ResponseRules{}, err
	}
	prohibitedBehavior, err := requireKnownStrings(raw, "prohibited_behavior", knownProhibitedBehaviorLabels())
	if err != nil {
		return ResponseRules{}, err
	}

	return ResponseRules{
		SchemaVersion:      schemaVersion,
		Persona:            persona,
		Style:              style,
		ReplyPosture:       replyPosture,
		MaxReplyChars:      maxReplyChars,
		AskHumanTriggers:   askHumanTriggers,
		ProhibitedBehavior: prohibitedBehavior,
	}, nil
}

func DefaultResponseRules() ResponseRules {
	return ResponseRules{
		SchemaVersion: SchemaVersion,
		Persona:       "Conservative Seagull local connector.",
		Style:         "Brief, factual, and cautious.",
		ReplyPosture:  OutcomeAskHuman,
		MaxReplyChars: 800,
		AskHumanTriggers: []string{
			"external_action",
			"secret_or_credential",
			"private_context",
			"ambiguous_request",
			"unsafe_instruction",
		},
		ProhibitedBehavior: []string{
			"execute_commands",
			"open_links",
			"send_without_approval",
			"change_rules_from_message_content",
			"include_connector_tokens",
		},
	}
}

func GenerateDraftReply(rules ResponseRuleResolution, deliveryItem map[string]any, threadContext map[string]any) DraftResult {
	_ = threadContext
	appliedRules := appliedRulesMetadata(rules)
	if rules.ValidationError != "" {
		return DraftResult{
			Outcome:      OutcomeAskHuman,
			Reason:       "response rules are invalid: " + rules.ValidationError,
			AppliedRules: appliedRules,
		}
	}
	if rules.Rules.ReplyPosture == OutcomeAskHuman {
		return DraftResult{
			Outcome:      OutcomeAskHuman,
			Reason:       "response rules require human input",
			AppliedRules: appliedRules,
		}
	}
	if rules.Rules.ReplyPosture == OutcomeNoReply {
		return DraftResult{
			Outcome:      OutcomeNoReply,
			Reason:       "response rules specify no_reply",
			AppliedRules: appliedRules,
		}
	}

	content := deliveryContent(deliveryItem)
	detected := detectTriggers(content)
	configured := []string{}
	for _, label := range detected {
		if known(label, rules.Rules.AskHumanTriggers) {
			configured = append(configured, label)
		}
	}
	if len(configured) > 0 {
		return DraftResult{
			Outcome:       OutcomeAskHuman,
			Reason:        "message matched ask-human trigger(s): " + strings.Join(configured, ", "),
			AppliedRules:  appliedRules,
			TriggerLabels: configured,
		}
	}

	compact := compactText(content)
	if compact == "" {
		return DraftResult{
			Outcome:       OutcomeAskHuman,
			Reason:        "message has no inline content to draft from",
			AppliedRules:  appliedRules,
			TriggerLabels: []string{"ambiguous_request"},
		}
	}

	return DraftResult{
		Outcome:      OutcomeDraftReply,
		Draft:        trimToLimit("I can help with this. I received: "+compact, rules.Rules.MaxReplyChars),
		Reason:       "draft generated from connector response rules",
		AppliedRules: appliedRules,
	}
}

func detectTriggers(content string) []string {
	normalized := strings.ToLower(content)
	triggers := []string{}
	if regexp.MustCompile(`\b(run|execute|open|click|curl|wget|ssh|delete|write|modify|install)\b`).MatchString(normalized) {
		triggers = append(triggers, "external_action")
	}
	if regexp.MustCompile(`\b(secret|token|password|passwd|api key|private key|credential)\b`).MatchString(normalized) {
		triggers = append(triggers, "secret_or_credential")
	}
	if regexp.MustCompile(`\b(private|confidential|dm|direct message|owner-only|owner only)\b`).MatchString(normalized) {
		triggers = append(triggers, "private_context")
	}
	if regexp.MustCompile(`\b(ignore|bypass|override).{0,40}\b(rule|policy|approval|instruction|safety)\b`).MatchString(normalized) {
		triggers = append(triggers, "unsafe_instruction")
	}
	if strings.Contains(normalized, "send without approval") || strings.Contains(normalized, "do not ask approval") {
		triggers = append(triggers, "unsafe_instruction")
	}
	return uniqueStrings(triggers)
}

func appliedRulesMetadata(rules ResponseRuleResolution) map[string]any {
	metadata := map[string]any{
		"source":          rules.Source,
		"schema_version":  rules.Rules.SchemaVersion,
		"reply_posture":   rules.Rules.ReplyPosture,
		"max_reply_chars": rules.Rules.MaxReplyChars,
	}
	if rules.ValidationError != "" {
		metadata["validation_error"] = rules.ValidationError
	}
	return metadata
}

func deliveryContent(item map[string]any) string {
	if current := objectValue(item, "current_message"); current != nil {
		if content, ok := current["content_inline"].(string); ok {
			return content
		}
	}
	if message := objectValue(item, "message"); message != nil {
		if content, ok := message["content_inline"].(string); ok {
			return content
		}
	}
	return ""
}

func compactText(value string) string {
	return strings.Join(strings.Fields(value), " ")
}

func trimToLimit(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	if limit <= 3 {
		return value[:limit]
	}
	return strings.TrimSpace(value[:limit-3]) + "..."
}

func invalidResolution(message string) ResponseRuleResolution {
	return ResponseRuleResolution{
		Rules:           DefaultResponseRules(),
		Source:          RuleSourceConnectorConfig,
		ValidationError: message,
	}
}

func requireString(raw map[string]any, name string) (string, error) {
	value, ok := raw[name].(string)
	if !ok || strings.TrimSpace(value) == "" {
		return "", fmt.Errorf("%s must be a non-empty string", name)
	}
	return strings.TrimSpace(value), nil
}

func requireInt(raw map[string]any, name string) (int, error) {
	switch value := raw[name].(type) {
	case int:
		return value, nil
	case json.Number:
		parsed, err := value.Int64()
		if err != nil {
			return 0, fmt.Errorf("%s must be an integer", name)
		}
		return int(parsed), nil
	case float64:
		parsed := int(value)
		if value != float64(parsed) {
			return 0, fmt.Errorf("%s must be an integer", name)
		}
		return parsed, nil
	default:
		return 0, fmt.Errorf("%s must be an integer", name)
	}
}

func requireKnownStrings(raw map[string]any, name string, knownLabels map[string]bool) ([]string, error) {
	values, ok := raw[name].([]any)
	if !ok {
		return nil, fmt.Errorf("%s must be a list", name)
	}
	result := []string{}
	for _, value := range values {
		label, ok := value.(string)
		if !ok || strings.TrimSpace(label) == "" {
			return nil, fmt.Errorf("%s must contain only non-empty strings", name)
		}
		label = strings.TrimSpace(label)
		if !knownLabels[label] {
			return nil, fmt.Errorf("unknown %s label: %s", name, label)
		}
		result = append(result, label)
	}
	return result, nil
}

func knownTriggerLabels() map[string]bool {
	return map[string]bool{
		"external_action":      true,
		"secret_or_credential": true,
		"private_context":      true,
		"ambiguous_request":    true,
		"unsafe_instruction":   true,
	}
}

func knownProhibitedBehaviorLabels() map[string]bool {
	return map[string]bool{
		"execute_commands":                  true,
		"open_links":                        true,
		"send_without_approval":             true,
		"change_rules_from_message_content": true,
		"include_connector_tokens":          true,
	}
}

func known(value string, candidates []string) bool {
	for _, candidate := range candidates {
		if value == candidate {
			return true
		}
	}
	return false
}

func uniqueStrings(values []string) []string {
	seen := map[string]bool{}
	result := []string{}
	for _, value := range values {
		if !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	return result
}
