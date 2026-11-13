pipeline {
    agent {
        label 'python && docker'
    }

    options {
        timestamps()
        skipDefaultCheckout(true)
    }

    environment {
        LLM_BASE_URL = 'https://api.xiaomimimo.com/v1'
        LLM_MODEL = 'mimo-v2.6-flash'
    }

    stages {

        stage('Checkout') {
            steps {
                echo 'Checking out source code from GitHub'

                checkout([
                    $class: 'GitSCM',
                    branches: [[name: '*/main']],
                    userRemoteConfigs: [[
                        url: 'https://github.com/yzha0219/devops-diagnostic-agent.git',
                        credentialsId: 'github-readonly'
                    ]]
                ])
            }
        }

        stage('Install Dependencies') {
            steps {
                sh '''
                    set -eu

                    WORKSPACE_REL="${WORKSPACE#"$JENKINS_AGENT_WORKDIR"/}"

                    docker run --rm \
                      --mount type=volume,source=jenkins_agent_workspace,target=/agent \
                      --workdir "/agent/${WORKSPACE_REL}" \
                      python:3.12-slim \
                      sh -lc '
                        set -eu
                        python -m venv .ci-venv
                        . .ci-venv/bin/activate
                        pip install --no-cache-dir -r requirements.txt
                    '
                '''
            }
        }

        stage('Run Pytest') {
            steps {
                sh '''
                    set -eu

                    WORKSPACE_REL="${WORKSPACE#"$JENKINS_AGENT_WORKDIR"/}"

                    docker run --rm \
                      --mount type=volume,source=jenkins_agent_workspace,target=/agent \
                      --workdir "/agent/${WORKSPACE_REL}" \
                      python:3.12-slim \
                      sh -lc '
                        set -eu
                        . .ci-venv/bin/activate
                        pytest -q
                    '
                '''
            }
        }

        stage('Evaluation and Regression') {
            steps {
                withCredentials([
                    string(
                        credentialsId: 'llm-api-key',
                        variable: 'LLM_API_KEY'
                    )
                ]) {
                    sh '''
                        set -eu

                        WORKSPACE_REL="${WORKSPACE#"$JENKINS_AGENT_WORKDIR"/}"

                        docker run --rm \
                          --mount type=volume,source=jenkins_agent_workspace,target=/agent \
                          --workdir "/agent/${WORKSPACE_REL}" \
                          -e LLM_API_KEY \
                          -e LLM_BASE_URL \
                          -e LLM_MODEL \
                          python:3.12-slim \
                          sh -lc '
                            set -eu

                            . .ci-venv/bin/activate

                            echo "Starting FastAPI..."

                            uvicorn app.main:app \
                              --host 0.0.0.0 \
                              --port 8000 \
                              > /tmp/agent-api.log 2>&1 &

                            API_PID=$!

                            cleanup() {
                                kill "$API_PID" 2>/dev/null || true
                                wait "$API_PID" 2>/dev/null || true
                            }

                            trap cleanup EXIT

                            echo "Waiting for API health check..."

                            python - <<'"'"'PY'"'"'
                            import time
                            import urllib.request

                            for attempt in range(30):
                                try:
                                    with urllib.request.urlopen(
                                        "http://127.0.0.1:8000/health",
                                        timeout=2
                                    ) as response:
                                        if response.status == 200:
                                            print("API is healthy")
                                            break
                                except Exception:
                                    time.sleep(1)
                            else:
                                raise SystemExit("API health check failed")
                            PY

                            echo "Running Agent Evaluation..."

                            python scripts/evaluate_agent.py

                            echo "Running Regression Test..."

                            python scripts/regression_test.py
                          '
                    '''
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts(
                artifacts: 'evaluation/latest_results.json',
                allowEmptyArchive: true
            )
        }

        success {
            echo 'AI Agent Quality Gate PASSED'
        }

        failure {
            echo 'AI Agent Quality Gate FAILED'
        }
    }
}
