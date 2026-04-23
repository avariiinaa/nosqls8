## Как запустить

1. **Запустите Neo4j** (через Docker):
   ```bash
	docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:latest
	python3 -m venv venv
	source venv/bin/activate
	pip install -r requirements.txt
	python import_data.py
	streamlit run app.py
	
	
	
	



