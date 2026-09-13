# 多阶段构建:Maven 打包 → JRE 运行
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build
COPY settings-docker.xml /root/.m2/settings.xml
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src ./src
RUN mvn -q -B clean package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
RUN apk add --no-cache wget >/dev/null 2>&1 || true
COPY --from=build /build/target/scg-gateway.jar /app/app.jar
EXPOSE 9080
HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
  CMD http_proxy= https_proxy= wget -qO- http://127.0.0.1:9080/actuator/health | grep -q UP || exit 1
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
