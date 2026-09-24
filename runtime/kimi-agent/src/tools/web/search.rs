use std::collections::HashMap;

use reqwest::header::HeaderMap;
use schemars::JsonSchema;
use serde::Deserialize;
use serde_json::Value;

use crate::constant::user_agent;
use crate::soul::toolset::get_current_tool_call_or_none;
use crate::tools::SkipThisTool;
use crate::tools::utils::{DEFAULT_MAX_CHARS, ToolResultBuilder, load_desc};

use kosong::tooling::{CallableTool2, ToolReturnValue};

const SEARCH_DESC: &str = include_str!("../desc/web/search.md");
const OPENROUTER_SNIPPET_CHARS: usize = 600;

#[derive(Debug, Deserialize, JsonSchema)]
pub struct SearchParams {
    #[schemars(description = "The query text to search for.")]
    pub query: String,
    #[serde(default = "default_search_limit")]
    #[schemars(
        description = "The number of results to return. Typically you do not need to set this value. When the results do not contain what you need, you probably want to give a more concrete query.",
        range(min = 1, max = 20),
        default = "default_search_limit"
    )]
    pub limit: i64,
    #[serde(default)]
    #[schemars(
        description = "Whether to include the content of the web pages in the results. It can consume a large amount of tokens when this is set to True. You should avoid enabling this when `limit` is set to a large value.",
        default
    )]
    pub include_content: bool,
}

fn default_search_limit() -> i64 {
    5
}

#[derive(Clone, Deserialize)]
struct SearchResult {
    title: String,
    url: String,
    snippet: String,
    #[serde(default)]
    content: String,
    #[serde(default)]
    date: String,
}

#[derive(Deserialize)]
struct SearchResponse {
    search_results: Vec<SearchResult>,
}

/// Where a search is sent. Moonshot's search service when configured, else
/// OpenRouter's `web` plugin on a chat completion.
enum SearchBackend {
    Moonshot {
        base_url: String,
        api_key: String,
        custom_headers: HashMap<String, String>,
    },
    OpenRouter {
        base_url: String,
        api_key: String,
        model: String,
        custom_headers: HashMap<String, String>,
    },
}

pub struct SearchWeb {
    description: String,
    backend: SearchBackend,
}

impl SearchWeb {
    pub fn new(runtime: &crate::soul::agent::Runtime) -> Result<Self, SkipThisTool> {
        let desc = load_desc(SEARCH_DESC, &[]);
        if let Some(service) = runtime.config.services.moonshot_search.clone() {
            return Ok(Self {
                description: desc,
                backend: SearchBackend::Moonshot {
                    base_url: service.base_url,
                    api_key: service.api_key,
                    custom_headers: service.custom_headers.unwrap_or_default(),
                },
            });
        }
        let service = runtime
            .config
            .services
            .openrouter_search
            .clone()
            .ok_or(SkipThisTool)?;
        let provider = runtime
            .llm
            .as_ref()
            .and_then(|llm| llm.provider_config.as_ref());
        let base_url = if service.base_url.trim().is_empty() {
            provider.map(|p| p.base_url.clone()).unwrap_or_default()
        } else {
            service.base_url
        };
        let api_key = if service.api_key.trim().is_empty() {
            provider.map(|p| p.api_key.clone()).unwrap_or_default()
        } else {
            service.api_key
        };
        let mut custom_headers = provider
            .and_then(|p| p.custom_headers.clone())
            .unwrap_or_default();
        custom_headers.extend(service.custom_headers.unwrap_or_default());
        Ok(Self {
            description: desc,
            backend: SearchBackend::OpenRouter {
                base_url,
                api_key,
                model: service.model,
                custom_headers,
            },
        })
    }

    async fn search_moonshot(
        &self,
        params: &SearchParams,
        base_url: &str,
        api_key: &str,
        custom_headers: &HashMap<String, String>,
    ) -> ToolReturnValue {
        let mut builder = ToolResultBuilder::new(DEFAULT_MAX_CHARS, None);

        if base_url.is_empty() || api_key.is_empty() {
            return builder.error(
                "Search service is not configured. You may want to try other methods to search.",
                "Search service not configured",
            );
        }

        let tool_call = match get_current_tool_call_or_none() {
            Some(call) => call,
            None => {
                return builder.error(
                    "Search service is not available without tool call context.",
                    "Search unavailable",
                );
            }
        };

        let mut headers = HeaderMap::new();
        headers.insert(reqwest::header::USER_AGENT, user_agent().parse().unwrap());
        headers.insert(
            reqwest::header::AUTHORIZATION,
            format!("Bearer {}", api_key).parse().unwrap(),
        );
        headers.insert("X-Msh-Tool-Call-Id", tool_call.id.parse().unwrap());
        insert_custom_headers(&mut headers, custom_headers);

        let client = reqwest::Client::new();
        let resp = match client
            .post(base_url)
            .headers(headers)
            .json(&serde_json::json!({
                "text_query": params.query,
                "limit": params.limit,
                "enable_page_crawling": params.include_content,
                "timeout_seconds": 30,
            }))
            .send()
            .await
        {
            Ok(resp) => resp,
            Err(err) => {
                return builder.error(
                    &format!(
                        "Failed to search. Error: {err}. This may indicates that the search service is currently unavailable."
                    ),
                    "Failed to search",
                );
            }
        };

        if resp.status() != reqwest::StatusCode::OK {
            return builder.error(
                &format!(
                    "Failed to search. Status: {}. This may indicates that the search service is currently unavailable.",
                    resp.status()
                ),
                "Failed to search",
            );
        }

        let payload: SearchResponse = match resp.json().await {
            Ok(payload) => payload,
            Err(err) => {
                return builder.error(
                    &format!(
                        "Failed to parse search results. Error: {err}. This may indicates that the search service is currently unavailable."
                    ),
                    "Failed to parse search results",
                );
            }
        };

        for (idx, result) in payload.search_results.into_iter().enumerate() {
            if idx > 0 {
                builder.write("---\n\n");
            }
            builder.write(&format!(
                "Title: {}\nDate: {}\nURL: {}\nSummary: {}\n\n",
                result.title, result.date, result.url, result.snippet
            ));
            if !result.content.is_empty() {
                builder.write(&format!("{}\n\n", result.content));
            }
        }

        builder.ok("", "")
    }

    async fn search_openrouter(
        &self,
        params: &SearchParams,
        base_url: &str,
        api_key: &str,
        model: &str,
        custom_headers: &HashMap<String, String>,
    ) -> ToolReturnValue {
        let mut builder = ToolResultBuilder::new(DEFAULT_MAX_CHARS, None);
        if base_url.trim().is_empty() || api_key.trim().is_empty() {
            return builder.error(
                "Search service is not configured. You may want to try other methods to search.",
                "Search service not configured",
            );
        }
        let url = format!("{}/chat/completions", base_url.trim_end_matches('/'));

        let mut headers = HeaderMap::new();
        headers.insert(reqwest::header::USER_AGENT, user_agent().parse().unwrap());
        headers.insert(
            reqwest::header::AUTHORIZATION,
            format!("Bearer {}", api_key).parse().unwrap(),
        );
        insert_custom_headers(&mut headers, custom_headers);

        let limit = params.limit.clamp(1, 20);
        let body = serde_json::json!({
            "model": model,
            "plugins": [{"id": "web", "max_results": limit}],
            "messages": [
                {
                    "role": "system",
                    "content": "You are a web search engine. Answer the query with a short factual summary of what the search results say, citing sources. Do not speculate beyond the results."
                },
                {"role": "user", "content": params.query},
            ],
            "max_tokens": 1500,
        });

        let resp = match reqwest::Client::new()
            .post(&url)
            .headers(headers)
            .json(&body)
            .send()
            .await
        {
            Ok(resp) => resp,
            Err(err) => {
                return builder.error(
                    &format!("Failed to search. Error: {err}. The search service may be unavailable."),
                    "Failed to search",
                );
            }
        };
        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().await.unwrap_or_default();
            return builder.error(
                &format!("Failed to search. Status: {status}. {text}"),
                "Failed to search",
            );
        }
        let payload: Value = match resp.json().await {
            Ok(payload) => payload,
            Err(err) => {
                return builder.error(
                    &format!("Failed to parse search results. Error: {err}."),
                    "Failed to parse search results",
                );
            }
        };

        let (summary, sources) = parse_openrouter_search(&payload);
        if summary.is_empty() && sources.is_empty() {
            return builder.error("The search returned no results.", "No results");
        }
        if !summary.is_empty() {
            builder.write(&format!("Summary: {summary}\n\n"));
        }
        for (idx, source) in sources.iter().enumerate() {
            if idx > 0 || !summary.is_empty() {
                builder.write("---\n\n");
            }
            builder.write(&format!("Title: {}\nURL: {}\n", source.title, source.url));
            if !source.content.is_empty() {
                let snippet = if params.include_content {
                    source.content.clone()
                } else {
                    truncate_chars(&source.content, OPENROUTER_SNIPPET_CHARS)
                };
                builder.write(&format!("Summary: {snippet}\n"));
            }
            builder.write("\n");
        }
        builder.ok("", "")
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WebSource {
    pub title: String,
    pub url: String,
    pub content: String,
}

/// The summary text and the de-duplicated `url_citation` sources of an
/// OpenRouter chat completion made with the `web` plugin.
pub fn parse_openrouter_search(payload: &Value) -> (String, Vec<WebSource>) {
    let message = payload
        .get("choices")
        .and_then(|choices| choices.get(0))
        .and_then(|choice| choice.get("message"));
    let summary = message
        .and_then(|m| m.get("content"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_string();
    let mut sources: Vec<WebSource> = Vec::new();
    let annotations = message
        .and_then(|m| m.get("annotations"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    for annotation in annotations {
        if annotation.get("type").and_then(Value::as_str) != Some("url_citation") {
            continue;
        }
        let citation = annotation.get("url_citation").unwrap_or(&annotation);
        let url = citation
            .get("url")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        if url.is_empty() || sources.iter().any(|s| s.url == url) {
            continue;
        }
        sources.push(WebSource {
            title: citation
                .get("title")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            url,
            content: citation
                .get("content")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
        });
    }
    (summary, sources)
}

fn insert_custom_headers(headers: &mut HeaderMap, custom: &HashMap<String, String>) {
    for (key, value) in custom {
        if let (Ok(name), Ok(val)) = (
            reqwest::header::HeaderName::from_bytes(key.as_bytes()),
            value.parse(),
        ) {
            headers.insert(name, val);
        }
    }
}

fn truncate_chars(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_string();
    }
    let mut out: String = text.chars().take(max).collect();
    out.push('…');
    out
}

#[async_trait::async_trait]
impl CallableTool2 for SearchWeb {
    type Params = SearchParams;

    fn name(&self) -> &str {
        "SearchWeb"
    }

    fn description(&self) -> &str {
        &self.description
    }

    async fn call_typed(&self, params: Self::Params) -> ToolReturnValue {
        match &self.backend {
            SearchBackend::Moonshot {
                base_url,
                api_key,
                custom_headers,
            } => {
                self.search_moonshot(&params, base_url, api_key, custom_headers)
                    .await
            }
            SearchBackend::OpenRouter {
                base_url,
                api_key,
                model,
                custom_headers,
            } => {
                self.search_openrouter(&params, base_url, api_key, model, custom_headers)
                    .await
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn openrouter_citations_become_deduplicated_sources() {
        let payload = json!({
            "choices": [{
                "message": {
                    "content": "  Rust 1.94 shipped in March.  ",
                    "annotations": [
                        {"type": "url_citation", "url_citation": {"url": "https://a.test", "title": "A", "content": "alpha"}},
                        {"type": "url_citation", "url_citation": {"url": "https://a.test", "title": "A again"}},
                        {"type": "file", "file": {}},
                        {"type": "url_citation", "url_citation": {"url": "https://b.test", "title": "B"}}
                    ]
                }
            }]
        });
        let (summary, sources) = parse_openrouter_search(&payload);
        assert_eq!(summary, "Rust 1.94 shipped in March.");
        assert_eq!(sources.len(), 2);
        assert_eq!(sources[0].title, "A");
        assert_eq!(sources[0].content, "alpha");
        assert_eq!(sources[1].url, "https://b.test");
    }

    #[test]
    fn a_reply_without_choices_is_empty() {
        let (summary, sources) = parse_openrouter_search(&json!({"error": "nope"}));
        assert!(summary.is_empty());
        assert!(sources.is_empty());
    }
}
