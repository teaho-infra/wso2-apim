package com.teaho.scg;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 纯动态路由网关:不声明任何静态 @Bean 路由。
 * 所有路由由 wso2-adapter 通过 /actuator/gateway/routes 热写入。
 */
@SpringBootApplication
public class ScgGatewayApplication {
    public static void main(String[] args) {
        SpringApplication.run(ScgGatewayApplication.class, args);
    }
}
