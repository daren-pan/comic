// ============================================================
//  comic 漫画聚合平台 —— Jenkins 流水线（服务器自建 Jenkins · 同机部署）
//
//  形态与 RuoYi-Cloud/Jenkinsfile-ecs 同一套路：构建机即部署机
//    1) 从 GitHub 拉代码（RuoYi 那份拉的是 Codeup，这里不一样），按 git diff 判断哪些模块变了
//    2) npm 构建前端产物（comic-web/dist）
//    3) deploy/build.sh 按序构建 5 个镜像（mysql → web → crawler → api → nginx）
//    4) 推送到阿里云 ACR（命名空间 comic-website）
//    5) 同机 docker compose 拉取新镜像并重启 → 自检
//
//  Jenkins 侧需要：
//    凭据  acr-credentials   ACR 用户名/口令（注入为 ACR_CREDENTIALS_USR / _PSW）
//          —— GitHub 那个仓库目前是公开的，拉代码不需要凭据；
//             若以后转私有，给 checkout 加 credentialsId: 'github-creds'（见第 1 步注释）
//    工具  NodeJS 名称为 node-18（vite 5 需要 Node 18+）
//
//  ⚠️ 跑之前必须确认的 5 件事：
//   1. COMIC_DEPLOY_DIR —— 服务器上**真实的部署目录**，里面必须有 .env。
//      .env 不入库（含 MYSQL_ROOT_PASSWORD / COMIC_JWT_SECRET），流水线不碰它，
//      但会把签出的 docker-compose.yml 覆盖到该目录，让编排定义跟着 git 走。
//   2. .env 里的 COMIC_DATA_HOST 必须是**绝对宿主路径**（如 /srv/comic/data）。
//      流水线会拦下相对路径 —— 留空/相对会被解析成别的目录，表现是"站点起来了但图库是空的"。
//   3. Jenkins 进程要能读到 COMIC_DEPLOY_DIR 这个路径。Jenkins 直接跑在宿主上 → 没问题；
//      Jenkins 跑在容器里（像 RuoYi 那样用 172.17.0.1 访问宿主）→ 该目录必须已挂进容器，
//      否则第 5 步会直接报"缺 .env"。这种情形见文件末尾「容器化 Jenkins 的替代做法」。
//   4. 服务器上 python3 要带 pip（deploy/build.sh 打 wheel 用；没有会回落到 crawler-service/.venv）。
//   5. 库里若已有旧数据，首次部署勾选 RUN_MIGRATE（老库缺 drop_fingerprint_unique 等迁移，
//      不迁的话第二个源的同名作品会 Duplicate entry 收不进来）。
// ============================================================
pipeline {
    agent any

    options {
        // 日志时间戳：Jenkins 装了 Timestamper 插件可以打开这行
        // timestamps()
        // 两次发布并发会把「构建 → 推送 → 重启」交错在一起，禁用并发
        disableConcurrentBuilds()
    }

    tools {
        nodejs 'node-18'
    }

    parameters {
        string(name: 'DEPLOY_TAG', defaultValue: '',
               description: '【回滚用】填一个已存在的镜像 tag（形如 b12-a1b2c3d），只做「拉取 + 重启」，跳过构建与推送。留空 = 正常构建发布')
        booleanParam(name: 'RUN_MIGRATE', defaultValue: false,
               description: '启动后对已有数据库跑一遍幂等迁移（tools/add_log_table.py / add_perf_indexes.py / drop_fingerprint_unique.py）。全新空库不需要')
        booleanParam(name: 'COLLECT', defaultValue: false,
               description: '本次是否连同定时采集（comic-scheduler）一起部署。开着 scheduler 就必须勾，否则它不会跟着换新镜像')
    }

    environment {
        // ---------- 镜像仓库：沿用 RuoYi 的 ACR 实例，只换命名空间 ----------
        ACR_REGISTRY    = 'crpi-zu4tna9y8drenzc4.cn-hangzhou.personal.cr.aliyuncs.com'
        ACR_NAMESPACE   = 'comic-website'
        REG             = "${ACR_REGISTRY}/${ACR_NAMESPACE}"
        ACR_CREDENTIALS = credentials('acr-credentials')

        // ---------- 服务器上的部署目录（含 .env），按实际路径改 ----------
        COMIC_DEPLOY_DIR = '/root/comic/deploy'

        // deploy/build.sh 里写死的本地镜像标签（别改，除非同时改了 build.sh）
        LOCAL_TAG = '1.0.0'
    }

    stages {

        // ============================================================
        // 1/5 拉代码 + 变更检测
        // ============================================================
        stage('■ 1/5 拉代码 & 检测变更') {
            steps {
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                echo '  📥 从 GitHub 拉取代码...'
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                // 公开仓库，匿名可读 —— 不传 credentialsId。
                // 若以后转成私有，在下面补一行：credentialsId: 'github-creds'
                git url: 'https://github.com/daren-pan/comic.git',
                    branch: 'main'

                script {
                    def GIT_HASH = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
                    env.UNIQUE_TAG = "b${BUILD_NUMBER}-${GIT_HASH}"
                    // 归一化回滚参数：老任务首次带参数构建时 params 可能为 null
                    env.EFFECTIVE_TAG = (params.DEPLOY_TAG ?: '').toString().trim()
                    echo "🏷️  本次镜像标签: ${env.UNIQUE_TAG}"
                    if (env.EFFECTIVE_TAG != '') {
                        echo "↩️  回滚模式：只部署 ${env.EFFECTIVE_TAG}（跳过 2~4 步）"
                    }

                    // ---- 变更检测只决定「推哪些镜像、动哪些容器」----
                    // 镜像本身一律全量重建：deploy/build.sh 是唯一的构建入口，5 层有固定
                    // 先后顺序，而且有 Docker 层缓存，重跑很便宜。做增量的目的是两件事 ——
                    // 不把 1GB 的 comic-mysql 每次重推一遍，以及不动没变的服务。
                    echo '🔍 检测哪些模块有变更...'
                    def DIFF = 'ALL'
                    try {
                        def oldCommit = sh(script: 'git rev-parse HEAD~1', returnStdout: true).trim()
                        DIFF = sh(script: "git diff --name-only ${oldCommit} HEAD", returnStdout: true).trim()
                    } catch (Exception e) { }
                    if (DIFF == '') { DIFF = 'ALL' }

                    // 构建脚本 / 编排定义变了 → 一律当全量，避免漏推
                    def INFRA = (DIFF == 'ALL') || DIFF.contains('deploy/build.sh') || DIFF.contains('deploy/docker-compose.yml')

                    env.CHANGED_WEB     = (INFRA || DIFF.contains('comic-web/'))      ? 'true' : 'false'
                    env.CHANGED_CRAWLER = (INFRA || DIFF.contains('crawler-service/')) ? 'true' : 'false'
                    env.CHANGED_API     = (INFRA || DIFF.contains('api-service/'))     ? 'true' : 'false'
                    env.CHANGED_NGINX   = (INFRA || DIFF.contains('deploy/nginx/'))    ? 'true' : 'false'
                    env.CHANGED_MYSQL   = (INFRA || DIFF.contains('deploy/mysql/')
                                                  || DIFF.contains('crawler-service/sql/')) ? 'true' : 'false'

                    // 依赖：comic-api 的 Dockerfile 是 `FROM comic-crawler` + `COPY --from comic-web`，
                    // 所以 crawler / web 任何一边变了，api 都必须跟着重建（前端是烘进 api 镜像的）
                    if (env.CHANGED_WEB == 'true' || env.CHANGED_CRAWLER == 'true') {
                        env.CHANGED_API = 'true'
                    }

                    echo "  Web=${env.CHANGED_WEB}  Crawler=${env.CHANGED_CRAWLER}  Api=${env.CHANGED_API}  Nginx=${env.CHANGED_NGINX}  Mysql=${env.CHANGED_MYSQL}"
                }
            }
        }

        // ============================================================
        // 2/5 npm 前端产物
        // ============================================================
        stage('■ 2/5 npm 前端产物') {
            when { expression { env.EFFECTIVE_TAG == '' } }
            steps {
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                echo '  🎨 构建前端 comic-web/dist...'
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                dir('comic-web') {
                    // 用 ci 而不是 install：node_modules 每次重建，避免残留出
                    // "vite: not found"（install 中断留下的残缺目录会一直骗过检查）
                    sh 'npm ci --registry=https://registry.npmmirror.com || npm install --registry=https://registry.npmmirror.com'
                    sh 'npm run build'
                }
                echo '  ✅ 前端构建完成'
            }
        }

        // ============================================================
        // 3/5 构建镜像（顺序固定在 deploy/build.sh）
        // ============================================================
        stage('■ 3/5 构建镜像') {
            when { expression { env.EFFECTIVE_TAG == '' } }
            steps {
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                echo '  🐳 deploy/build.sh（mysql → web → crawler → api → nginx）'
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                // 容器内 pip 源：国内服务器把下面 withEnv 的**两行一起**取消注释会快很多
                // （deploy/build.sh 认这个环境变量）；不打开则容器内走 pypi.org 官方源。
                // withEnv(['PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple']) {
                sh 'bash deploy/build.sh'
                // }
                echo '  ✅ 5 个镜像已就绪'
            }
        }

        // ============================================================
        // 4/5 推送 ACR
        // ============================================================
        stage('■ 4/5 推送 ACR') {
            when { expression { env.EFFECTIVE_TAG == '' } }
            steps {
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                echo '  🔐 登录 ACR + 按需推送...'
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                // 单引号：让 shell 去展开变量，Groovy 不插值（口令不会进日志）
                sh 'echo "$ACR_CREDENTIALS_PSW" | docker login --username "$ACR_CREDENTIALS_USR" --password-stdin $ACR_REGISTRY'

                script {
                    // 本地名（comic-api:1.0.0）→ 仓库名（<REG>/comic-api:<tag>）
                    def pushImg = { repo ->
                        echo "  📤 ${repo} → ${env.REG}/${repo}:${env.UNIQUE_TAG}"
                        sh "docker tag ${repo}:${env.LOCAL_TAG} ${env.REG}/${repo}:${env.UNIQUE_TAG}"
                        sh "docker push ${env.REG}/${repo}:${env.UNIQUE_TAG}"
                        // latest 只是方便临时拉取（比如另起一套环境）；部署永远用不可变 tag
                        sh "docker tag ${repo}:${env.LOCAL_TAG} ${env.REG}/${repo}:latest"
                        sh "docker push ${env.REG}/${repo}:latest"
                    }

                    if (env.CHANGED_WEB     == 'true') pushImg('comic-web')      // api 的 COPY --from 来源，得留着
                    if (env.CHANGED_CRAWLER == 'true') pushImg('comic-crawler')
                    if (env.CHANGED_API     == 'true') pushImg('comic-api')
                    if (env.CHANGED_NGINX   == 'true') pushImg('comic-nginx')
                    // comic-mysql 只在 schema / my.cnf 变时才推 —— 它 1.09GB，每次推纯属浪费
                    if (env.CHANGED_MYSQL   == 'true') pushImg('comic-mysql')
                }
            }
        }

        // ============================================================
        // 5/5 部署 + 自检（同机 docker compose）
        // ============================================================
        stage('■ 5/5 部署 & 自检') {
            steps {
                script {
                    def DEPLOY_DIR = env.COMIC_DEPLOY_DIR
                    def TAG        = env.EFFECTIVE_TAG != '' ? env.EFFECTIVE_TAG : env.UNIQUE_TAG
                    def PROFILE    = (params.COLLECT ? '--profile collect ' : '')
                    echo "🚀 部署 tag: ${TAG}${PROFILE ? '（含定时采集）' : ''}"

                    // 回滚路径没有走第 4 步的登录，这里补一次（幂等）
                    sh 'echo "$ACR_CREDENTIALS_PSW" | docker login --username "$ACR_CREDENTIALS_USR" --password-stdin $ACR_REGISTRY'

                    echo ">>> 部署目录：${DEPLOY_DIR}"
                    sh """
                        mkdir -p '${DEPLOY_DIR}'
                        # 编排定义随 git 走（-ef 兜住"部署目录恰好就是签出目录"的同文件情形）
                        if [ ! deploy/docker-compose.yml -ef '${DEPLOY_DIR}/docker-compose.yml' ]; then
                          cp deploy/docker-compose.yml '${DEPLOY_DIR}/docker-compose.yml'
                        fi
                        if [ ! -f '${DEPLOY_DIR}/.env' ]; then
                          echo "!! 部署目录缺少 .env：${DEPLOY_DIR}/.env"
                          echo "   从 deploy/.env.example 复制一份，填好 MYSQL_ROOT_PASSWORD 与 COMIC_JWT_SECRET 再重跑"
                          exit 1
                        fi
                        echo "   docker-compose.yml 已同步，.env 就位 ✅"
                    """

                    // 闸门：COMIC_DATA_HOST 必须是绝对宿主路径。
                    // bind 挂载用的是宿主路径；留空或相对路径会被解析到别处，
                    // 表现是"站点正常但图库空的 / 转存落不了盘"——很难查，所以在这里直接拦下。
                    sh """
                        DH=\$(grep -E '^COMIC_DATA_HOST=' '${DEPLOY_DIR}/.env' | tail -1 | cut -d= -f2- || true)
                        case "\$DH" in
                          /*) echo "   COMIC_DATA_HOST = \$DH ✅" ;;
                          *)  echo "!! COMIC_DATA_HOST 必须是绝对宿主路径（当前：'\$DH'）"
                              echo "   请在 ${DEPLOY_DIR}/.env 里设成例如：COMIC_DATA_HOST=/srv/comic/data"
                              exit 1 ;;
                        esac
                    """

                    // 从 ACR 拉回本次要用的镜像，再还原成本地规范名 ——
                    // 这样 docker-compose.yml 里继续写 `comic-api:1.0.0`，本地直跑那套
                    // （up.sh / build.sh）完全不受影响，不用为上线改造 compose。
                    def syncImg = { repo ->
                        echo "  📥 ${env.REG}/${repo}:${TAG}"
                        sh "docker pull ${env.REG}/${repo}:${TAG}"
                        sh "docker tag ${env.REG}/${repo}:${TAG} ${repo}:${env.LOCAL_TAG}"
                    }
                    syncImg('comic-api')
                    syncImg('comic-nginx')
                    syncImg('comic-crawler')      // 定时采集用它，且是 api 的基础镜像层
                    if (env.CHANGED_MYSQL == 'true') {
                        syncImg('comic-mysql')     // 1GB，只在 schema 变时才拉
                    }

                    // compose 会自己比对镜像 ID，只重建真正换了的容器 ——
                    // 没变的服务（比如 mysql）不会被重启
                    sh "cd '${DEPLOY_DIR}' && docker compose ${PROFILE}up -d"
                    sh "cd '${DEPLOY_DIR}' && docker compose ${PROFILE}ps"

                    if (params.RUN_MIGRATE) {
                        echo '>>> 迁移已有库（幂等，重复跑不会重复改）'
                        sh """
                            set -e
                            cd '${DEPLOY_DIR}'
                            mkdir -p tools
                            cp -r '${env.WORKSPACE}/tools/.' tools/
                            for t in add_log_table.py add_perf_indexes.py drop_fingerprint_unique.py; do
                              echo "   → tools/\$t"
                              docker compose run --rm -v ./tools:/app/tools:ro comic-app python "tools/\$t"
                            done
                            echo '   ✅ 迁移脚本跑完'
                        """
                    }

                    // 硬自检：在容器内部打自己的接口（不依赖宿主有没有 curl）
                    sh """
                        cd '${DEPLOY_DIR}'
                        docker compose exec -T comic-app python -c "import urllib.request,json;print('   comic-app /api/health →',json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=10))['data'])"
                    """

                    // 软自检：对外入口的 HTTP 码（nginx 在上游就绪前会 502，所以重试几轮再看）
                    sh """
                        cd '${DEPLOY_DIR}'
                        PORT=\$(grep -E '^HTTP_PORT=' .env | tail -1 | cut -d= -f2- || true)
                        PORT=\${PORT:-80}
                        CODE=''
                        for i in \$(seq 1 12); do
                          CODE=\$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:\$PORT/" || true)
                          case "\$CODE" in 000|502|503|504|"") sleep 3 ;; *) break ;; esac
                        done
                        echo "   对外入口 http://127.0.0.1:\$PORT/ → HTTP \${CODE}"
                        case "\$CODE" in
                          200) : ;;
                          *) echo "   ⚠️ 返回 \${CODE} —— 502 多为上游还没就绪，过几秒再试；持续异常看：docker compose logs comic-app" ;;
                        esac
                    """
                    echo '  ✅ 部署完成'
                }
            }
        }
    }

    post {
        success {
            echo ''
            echo '╔══════════════════════════════════════════╗'
            echo "║  ✅ comic Pipeline #${BUILD_NUMBER} 成功！"
            echo "║  镜像 tag: ${env.UNIQUE_TAG}"
            echo '╚══════════════════════════════════════════╝'
            echo "  回滚：用 ${env.UNIQUE_TAG} 之前的一个 tag 触发一次带 DEPLOY_TAG 的构建即可"
        }
        failure {
            echo ''
            echo '╔══════════════════════════════════════════╗'
            echo "║  ❌ comic Pipeline #${BUILD_NUMBER} 失败！"
            echo '╚══════════════════════════════════════════╝'
        }
    }
}

// ================================================================
//  容器化 Jenkins 的替代做法（只有在第 5 步报「缺 .env」时才需要）
//
//  若 Jenkins 是跑在容器里的（像 RuoYi-Cloud/Jenkinsfile-ecs 那样用 172.17.0.1
//  访问宿主），它看不到宿主的 /root/comic/deploy。两种解法：
//
//  解法 A（推荐）：把宿主目录挂进 Jenkins 容器，让 COMIC_DEPLOY_DIR 真实可见，
//    上面第 5 步一行都不用改。
//
//  解法 B：把第 5 步那段改成走 ssh 在宿主上执行，与 RuoYi-ecs 一致 ——
//    withCredentials([sshUserPrivateKey(credentialsId: 'ecs-ssh-key',
//        keyFileVariable: 'SSH_KEY', usernameVariable: '')]) {
//      sh """
//        ssh -o StrictHostKeyChecking=no -i \$SSH_KEY root@172.17.0.1 '
//          cd /root/comic/deploy &&
//          docker pull ${REG}/comic-api:${TAG} &&
//          docker tag  ${REG}/comic-api:${TAG} comic-api:1.0.0 &&
//          docker compose up -d'
//      """
//    }
//    ⚠️ 走 ssh 时，第 3 步 `bash deploy/build.sh` 里的 docker build 仍可在
//       Jenkins 容器内完成（构建上下文由 CLI 打包发给 daemon），但第 4 步推送前
//       必须确认 Jenkins 里的 docker 与宿主是**同一个 daemon**，否则推的是两个仓库。
// ================================================================
