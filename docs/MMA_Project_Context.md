# MMA Intelligence App: Project Context

## Who I am
- Ali Shana'a, Data Scientist (Consultant) at IQVIA in Amsterdam, working in pharma strategy consulting since 2022.
- MSc Statistics and Data Science (KU Leuven); BSc Applied Mathematics and BBA Finance (AUB).
- Comfortable with: Python (pandas, scikit-learn), SQL, R, Spark, Databricks pipelines and workflows, Azure, Git, REST APIs, Dash, LangChain, LLM applications, web scraping, OCR and LLM extraction, time series and predictive modelling, explainable AI.
- Less experienced with: owning a production system end to end, software architecture, CI/CD, evaluation of GenAI systems, diagnosing chatbot and agent failures, multi-agent systems, Text2SQL, DSPy, fine-tuning, PyTorch, monitoring, and building for real users.
- I train no-gi jiu-jitsu and follow MMA closely, so I understand the domain.

## Why this project exists
Two goals, in this order:

1. **General upskilling in modern AI.** Learn how to build, diagnose, evaluate and improve real AI systems, especially chatbots and agents, in a way that transfers across tools and employers.
2. **A concrete career target.** In October 2026 I had a recruiter screen for the AI Engineer – Forward Deployed Engineer (FDE) role at Databricks in Amsterdam. The recruiter advised me to get about 6 months of experience architecting end-to-end solutions and come back. I can't realistically get this at work right now (I'm asking a senior about a possible work project in parallel), so this project builds it.

Target: by around March 2027, have designed, built, deployed and operated a real end-to-end AI system with real users, and be able to explain every architecture decision and every evaluation result in an interview, whether at Databricks or elsewhere.

## Learning goals (modern AI skills)
- **Building chatbots and agents:** prompt design, RAG (chunking, embeddings, retrieval, reranking), tool use, Text2SQL, multi-step agents, guardrails.
- **Diagnosing problems:** tracing every call, inspecting retrieval and intermediate steps, error analysis on real conversations, building a catalogue of failure modes (hallucination, wrong retrieval, bad SQL, refusals, latency).
- **Evaluating outcomes:** curated eval sets, automated metrics, LLM-as-judge (and checking the judge against human labels), human feedback from users, regression testing before each change.
- **Improving systematically:** change one thing, re-run evals, compare; prompt optimisation (e.g. DSPy); knowing when fine-tuning is or isn't worth it.
- **Operating in production:** monitoring quality, cost and latency; logging user feedback; versioning prompts and models; secrets and governance.
- **Classic ML alongside GenAI:** the prediction model, with proper validation, calibration and explanations.

## What the Databricks FDE role values (one target, not the only one)
- Building GenAI applications: RAG, multi-agent systems, Text2SQL, fine-tuning, using tools like HuggingFace, LangChain and DSPy.
- Deploying production-grade GenAI applications, including evaluation and optimisation.
- Hands-on data science with pandas, scikit-learn, PyTorch.
- Production ML deployments on a cloud (AWS, Azure or GCP).
- Communicating technical concepts to technical and non-technical audiences.
- Preferred: Databricks platform and Apache Spark experience.
- Relevant Databricks components to use where sensible: Unity Catalog, Delta Lake, Lakeflow (pipelines, jobs), Vector Search, Model Serving, Mosaic AI / Agent Bricks, MLflow (tracing, GenAI evaluation, model registry), Databricks Apps, Genie, Lakebase, Unity AI Gateway.

## The product idea
An MMA intelligence app for fans, built on Databricks, in phases:

1. **Fighter stats foundation:** fighter profiles and fight history ingested into Delta tables and shown in a dashboard app (like existing stats sites).
2. **News and interview intelligence:** scrape or ingest news articles and interviews per fighter; use LLMs to generate a "recent news" section and strengths/weaknesses insights per fighter.
3. **"Ask the stats" chatbot/agent:** a Text2SQL (and possibly RAG) agent so users can ask natural-language questions about fighters and fights. This is the main vehicle for learning to build, diagnose and evaluate chatbots.
4. **Fight prediction model:** predict fight outcomes with explanations, evaluated against bookmaker implied probabilities as a baseline.
5. **Real users, monitoring and iteration** throughout, not only at the end.

## Principles for how it should be built
- Treat it as an AI system, not just a dashboard. The value is in the architecture decisions, the LLM pipeline, evaluation, diagnosis, monitoring, cost and governance.
- End to end means owning every layer: ingestion (scheduled and incremental), storage and governance, LLM enrichment, retrieval and agents, ML model, evaluation, serving and the app, monitoring and cost, and documentation.
- **Evaluation-driven development:** no LLM feature ships without an eval set and a baseline score; every change is compared against it.
- **Observe before fixing:** trace and log everything, and diagnose failures from real data rather than guessing.
- **Choose tools on merit:** Databricks-native where sensible, but understand the underlying concepts and the common open-source alternatives so the skills transfer.
- Keep a written architecture decision log (options considered, trade-off, decision, what I'd change at scale) and a learning log of failures found and how they were fixed.
- Get real users early (friends, people at my gym, an online MMA community) and iterate based on their feedback.
- Differentiate from existing sites (UFCStats, Tapology, Sherdog) through the AI layer: insights, Q&A and explained predictions.
- Prefer patterns that mirror real enterprise work, so the project produces believable interview stories.

## Platform: Databricks Free Edition (checked 27 October 2026)
Personal Free Edition account, not my work instance. Source: https://docs.databricks.com/aws/en/getting-started/free-edition-limitations

What fits within Free Edition:
- Serverless compute only (no custom clusters); notebook compute is limited in size and usage.
- One SQL warehouse, 2X-Small.
- Up to 5 concurrent job tasks; one active Lakeflow pipeline per pipeline type.
- One Vector Search (AI Search) endpoint with one search unit; no Direct Vector Access.
- Foundation Model APIs available, but some models are not; no provisioned throughput.
- Model serving: limited number of endpoints, no GPU serving, no custom models on GPU, no batch inference. CPU-based prediction models are fine.
- Up to 3 Databricks Apps.
- Non-commercial use only.

Limits that shape the architecture:
- **Outbound internet is restricted to a limited set of trusted domains**, so scraping news sites from inside Databricks will probably fail.
- **Databricks Apps stop automatically 24 hours after being started or redeployed**, and the docs don't say whether users outside the workspace can access them (likely they need to sign in to the workspace).
- **Fair usage policy:** exceeding the quota shuts compute down for the rest of the day (in extreme cases, the month). Data is kept.
- No SLA or support; inactive accounts may be deleted after a long period.
- LinkedIn verification can raise some usage limits.

Agreed approach (hybrid):
- **Scraping runs outside Databricks** (laptop or a free scheduler such as GitHub Actions) and pushes raw results into a Unity Catalog volume. Databricks takes over from the landing zone onwards. This mirrors a realistic enterprise pattern (external source system, landing zone, governed lakehouse).
- **Data, pipelines, LLM enrichment, Vector Search, Text2SQL agent, prediction model, evaluation and monitoring live on Databricks.**
- **A lightweight public frontend is hosted outside Databricks** (for example Streamlit Community Cloud) and calls Databricks through its APIs (SQL Statement Execution API, serving endpoints) with a service credential, so real users don't need workspace accounts.
- A Databricks App can still be used for an internal admin or monitoring view.
- Revisit a small paid workspace only if real usage outgrows Free Edition.

Still to verify:
- Whether Databricks Apps can be opened by users outside the workspace on Free Edition.
- Which domains are on the outbound allowlist (some sources may be reachable directly).
- Which foundation models and how many serving endpoints are available.
- How to authenticate the external frontend and scraper securely (token or service principal options on Free Edition) and keep secrets out of code.

## Other constraints
- Budget: personal project, keep costs low.
- Time: evenings and weekends alongside a full-time job.
- Scraping: respect each site's terms of use and robots.txt; prefer official feeds, RSS or APIs; store summaries and links rather than full article text.
- Predictions are presented as analysis, not betting advice.

## Status
- 27 October 2026: Decided on the MMA project as the main side project. Checked Free Edition limits and agreed the hybrid approach above. Earlier pharma RAG project (public GLP-1 NICE/EMA documents) is now secondary.
- 28 October 2026: Broadened the goal from Databricks/FDE preparation to general modern-AI upskilling, with emphasis on building, diagnosing and evaluating chatbots and agents.
- Nothing built yet for the MMA app. Next: verify the open points above, then design the phase 1 architecture.

## Outputs I want along the way
- A working, deployed app with real users.
- An architecture diagram and decision log.
- An evaluation harness: eval sets and metrics for the LLM insights, the chatbot/Text2SQL agent and the prediction model, run on every change.
- A failure-mode catalogue for the chatbot: what went wrong, how it was diagnosed, how it was fixed, and the before/after scores.
- 3–5 STAR stories from the build (problems hit, trade-offs made, what users taught me).
- Optionally, a short write-up or talk I could share publicly.
