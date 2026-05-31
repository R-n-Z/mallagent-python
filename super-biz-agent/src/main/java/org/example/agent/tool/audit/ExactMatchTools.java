package org.example.agent.tool.audit;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * 关键词精确匹配工具（三层漏斗）
 * 1. 精确匹配 — O(1) hash lookup
 * 2. 同义词扩展 — 词典映射
 * 3. 字符模糊匹配 — 编辑距离（仅短词）
 */
@Component
public class ExactMatchTools {

    private static final Logger logger = LoggerFactory.getLogger(ExactMatchTools.class);

    public static final String TOOL_EXACT_MATCH_KEYWORDS = "exactMatchKeywords";

    @Value("${rule.rag.fuzzy.max-relative-distance:0.35}")
    private double maxRelativeDistance;

    @Value("${rule.rag.fuzzy.max-keyword-length:10}")
    private int maxKeywordLength;

    private final ObjectMapper objectMapper = new ObjectMapper();

    /** 精确匹配词 → 规则信息 */
    private final Map<String, JsonNode> exactIndex = new HashMap<>();
    /** 同义词 → 原始关键词 */
    private final Map<String, String> synonymMap = new HashMap<>();
    /** 短词列表（用于编辑距离） */
    private final List<String> shortKeywords = new ArrayList<>();

    @PostConstruct
    public void init() {
        try {
            ClassPathResource resource = new ClassPathResource("audit/rules.json");
            String content = resource.getContentAsString(StandardCharsets.UTF_8);
            JsonNode root = objectMapper.readTree(content);

            // 索引 escalationKeywords
            for (JsonNode kw : root.get("escalationKeywords")) {
                String word = kw.get("keyword").asText().toLowerCase();
                exactIndex.put(word, kw);
                if (word.length() <= maxKeywordLength) shortKeywords.add(word);
                indexSynonyms(kw, word);
            }
            // 索引 strictRejectRules.productKeywords
            for (JsonNode rule : root.get("strictRejectRules")) {
                for (JsonNode kw : rule.get("productKeywords")) {
                    String word = kw.asText().toLowerCase();
                    exactIndex.put(word, rule);
                    if (word.length() <= maxKeywordLength) shortKeywords.add(word);
                    indexSynonyms(kw, word);
                }
            }
            // 索引 autoApproveRules.allowedReasons（使长词拼写错误可被L3捕获）
            for (JsonNode rule : root.get("autoApproveRules")) {
                for (JsonNode kw : rule.get("allowedReasons")) {
                    String word = kw.asText().toLowerCase();
                    exactIndex.put(word, rule);
                    if (word.length() <= maxKeywordLength) shortKeywords.add(word);
                    indexSynonyms(kw, word);
                }
            }
            logger.info("精确匹配索引构建完成: exact={}, synonyms={}, short={}",
                    exactIndex.size(), synonymMap.size(), shortKeywords.size());
        } catch (Exception e) {
            logger.error("精确匹配索引构建失败", e);
        }
    }

    private void indexSynonyms(JsonNode node, String keyword) {
        if (node.isObject() && node.has("synonyms")) {
            for (JsonNode syn : node.get("synonyms")) {
                synonymMap.putIfAbsent(syn.asText().toLowerCase(), keyword);
            }
        }
    }

    @Tool(name = TOOL_EXACT_MATCH_KEYWORDS,
          description = "精确匹配规则关键词（含同义词扩展和错别字模糊匹配）。输入一段文本，返回命中的规则关键词及其匹配方式")
    public String exactMatchKeywords(
            @ToolParam(description = "需要检查的文本") String text) {
        if (text == null || text.trim().isEmpty()) {
            return "{\"matches\": []}";
        }
        String lower = text.toLowerCase();
        List<Map<String, Object>> matches = new ArrayList<>();

        // 第一层：精确匹配
        for (Map.Entry<String, JsonNode> entry : exactIndex.entrySet()) {
            if (lower.contains(entry.getKey())) {
                matches.add(buildMatchResult(entry.getKey(), entry.getValue(), "exact", 1.0));
            }
        }

        // 第二层：同义词匹配
        for (Map.Entry<String, String> entry : synonymMap.entrySet()) {
            if (lower.contains(entry.getKey())) {
                JsonNode rule = exactIndex.get(entry.getValue());
                // 避免同义词与精确匹配重复
                boolean alreadyExact = matches.stream()
                        .anyMatch(m -> m.get("keyword").equals(entry.getValue()));
                if (!alreadyExact) {
                    matches.add(buildMatchResult(entry.getValue(), rule, "synonym", 0.9));
                }
            }
        }

        // 第三层：编辑距离模糊匹配（仅 ≥4 字长词，拼写错误）
        // 设计：≤3字词走同义词词典（第二层），模糊匹配合法词汇间互扰太大。
        // ≥4字长词(如"物流损坏""质量问题"): 相对编辑距离≤35%视为拼写错误。
        for (String keyword : shortKeywords) {
            if (keyword.length() < 4) continue;  // ≤3字词跳过，走第二层同义词

            boolean alreadyMatched = matches.stream()
                    .anyMatch(m -> m.get("keyword").equals(keyword));
            if (alreadyMatched) continue;

            int kwLen = keyword.length();
            for (int i = 0; i <= lower.length() - Math.max(1, kwLen - 2); i++) {
                int maxEnd = Math.min(lower.length(), i + kwLen + 2);
                for (int end = Math.max(i + kwLen - 2, i + 1); end <= maxEnd; end++) {
                    String substr = lower.substring(i, end);
                    int subLen = substr.length();
                    if (Math.abs(subLen - kwLen) > 1) continue;

                    int dist = levenshtein(keyword, substr);
                    double relativeDist = (double) dist / Math.max(kwLen, subLen);
                    if (relativeDist <= maxRelativeDistance) {
                        JsonNode rule = exactIndex.get(keyword);
                        matches.add(buildMatchResult(keyword, rule, "fuzzy", 0.7));
                        i = lower.length();
                        break;
                    }
                }
            }
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("totalMatches", matches.size());
        result.put("matches", matches);
        try { return objectMapper.writeValueAsString(result); }
        catch (Exception e) { return "{\"matches\": []}"; }
    }

    private Map<String, Object> buildMatchResult(String keyword, JsonNode rule, String source, double score) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("keyword", keyword);
        m.put("source", source);
        m.put("score", score);
        if (rule != null) {
            m.put("category", rule.has("category") ? rule.get("category").asText() : "");
            m.put("priority", rule.has("priority") ? rule.get("priority").asText() : "");
            m.put("ruleId", rule.has("ruleId") ? rule.get("ruleId").asText() : "");
        }
        return m;
    }

    private int levenshtein(String a, String b) {
        int[][] dp = new int[a.length() + 1][b.length() + 1];
        for (int i = 0; i <= a.length(); i++) dp[i][0] = i;
        for (int j = 0; j <= b.length(); j++) dp[0][j] = j;
        for (int i = 1; i <= a.length(); i++) {
            for (int j = 1; j <= b.length(); j++) {
                int cost = a.charAt(i - 1) == b.charAt(j - 1) ? 0 : 1;
                dp[i][j] = Math.min(Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1), dp[i - 1][j - 1] + cost);
            }
        }
        return dp[a.length()][b.length()];
    }
}
